# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Maintenance-mode gate.

Reads the ``system`` namespace from ``app_settings``. When
``maintenance_mode`` is ``True`` the middleware short-circuits every
request with HTTP 503 except:

* a small bypass list (health probes, the public app-config bundle,
  the auth endpoints super-admins need to flip the flag back), and
* requests carrying a valid auth cookie whose user holds the
  ``super_admin`` role.

The session lookup is hot — it runs on every request — so the
maintenance flag is cached in-process for ``_TTL_SECONDS``. Two
seconds is short enough that flipping the flag in the admin UI feels
instant on the next page load, while still preventing a DB round-trip
on every static request when maintenance is off (the common case).
"""
from __future__ import annotations

import time
from typing import Final

import jwt
from fastapi import Request, Response
from fastapi_users.jwt import decode_jwt
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware

from app.db import get_session_factory
from app.logging import log
from app.models.auth_session import AuthSession
from app.models.ops import AppSetting
from app.models.rbac import Role, role_permissions, user_roles
from app.settings import get_settings

# Endpoints that must remain reachable when maintenance is on. Health
# probes for monitoring; /app-config so the frontend can render the
# maintenance page itself; the JWT login + 2FA flow so a super_admin
# can sign in to disable maintenance; /users/me so the client knows
# whether the current cookie is super_admin.
BYPASS_PATHS: Final = frozenset({
    "/healthz",
    "/readyz",
    "/health",
    "/app-config",
    "/auth/jwt/login",
    "/auth/jwt/logout",
    "/users/me",
    "/users/me/context",
})

_BYPASS_PREFIXES: Final = ("/auth/totp/", "/auth/email-otp/", "/auth/webauthn/")

_TTL_SECONDS: Final = 2.0
_cache: dict[str, object] = {"flag": False, "message": "", "expires_at": 0.0}


async def _read_system_flag() -> tuple[bool, str]:
    """Look up ``app_settings['system']``. Fail open on any error.

    A fresh deployment that hasn't run alembic yet has no
    ``app_settings`` table — and the smoke flow's ``/readyz`` poll
    can't migrate until the API answers. If we 500 on the missing
    table, the pre-migration readiness check loops forever. Same
    posture if the DB is briefly unreachable: better to admit traffic
    than to lock the platform down on transient infra issues.
    """
    try:
        factory = get_session_factory()
        async with factory() as session:
            raw = (
                await session.execute(
                    select(AppSetting.value).where(AppSetting.key == "system")
                )
            ).scalar_one_or_none()
    except Exception as exc:
        log.warning("maintenance.read_failed", error=str(exc))
        return False, ""
    if raw is None:
        return False, ""
    return bool(raw.get("maintenance_mode")), str(raw.get("maintenance_message", ""))


async def _get_flag() -> tuple[bool, str]:
    now = time.monotonic()
    if now < float(_cache["expires_at"]):
        return bool(_cache["flag"]), str(_cache["message"])
    flag, message = await _read_system_flag()
    _cache["flag"] = flag
    _cache["message"] = message
    _cache["expires_at"] = now + _TTL_SECONDS
    return flag, message


async def _is_super_admin(token: str | None) -> bool:
    if not token:
        return False
    settings = get_settings()
    try:
        data = decode_jwt(
            token,
            settings.jwt_secret,
            ["fastapi-users:auth"],
            algorithms=["HS256"],
        )
    except jwt.PyJWTError:
        return False
    user_id = data.get("sub")
    session_id = data.get("sid")
    if user_id is None or session_id is None:
        return False
    factory = get_session_factory()
    async with factory() as session:
        # Cookie has to map to a live, full-2FA session.
        sess = (
            await session.execute(
                select(AuthSession).where(AuthSession.session_id == session_id)
            )
        ).scalar_one_or_none()
        if sess is None or sess.revoked_at is not None:
            return False
        # super_admin is the only role we care about for the bypass.
        result = await session.execute(
            select(Role.code)
            .select_from(user_roles)
            .join(Role, Role.id == user_roles.c.role_id)
            .where(user_roles.c.user_id == int(user_id), Role.code == "super_admin")
            .limit(1)
        )
        return result.scalar_one_or_none() is not None


def _is_bypass_path(path: str) -> bool:
    if path in BYPASS_PATHS:
        return True
    return any(path.startswith(p) for p in _BYPASS_PREFIXES)


# Imported by tests to reset the cache between cases.
def reset_cache() -> None:
    _cache["flag"] = False
    _cache["message"] = ""
    _cache["expires_at"] = 0.0


# Re-export role_permissions even if unused by name, so the import keeps
# the test fixtures' RBAC table on the SQLAlchemy registry. (Safety
# valve: removing this without verifying alembic still emits the table
# is the kind of change that silently breaks tests.)
_ = role_permissions


class MaintenanceMiddleware(BaseHTTPMiddleware):
    """503-everything-except-super-admin when ``system.maintenance_mode``
    is on. Off by default, so the hot-path cost is one cache hit and
    nothing else."""

    async def dispatch(self, request: Request, call_next):
        # Bypass-path check FIRST — it's free and avoids hitting the DB
        # on /healthz, /readyz, the auth flow, and /app-config. The
        # smoke-up flow polls /readyz before running alembic, so a DB
        # query here would deadlock the bring-up sequence.
        path = request.url.path
        if _is_bypass_path(path):
            return await call_next(request)

        flag, message = await _get_flag()
        if not flag:
            return await call_next(request)

        token = request.cookies.get("atrium_auth")
        if await _is_super_admin(token):
            return await call_next(request)

        log.info("maintenance.blocked", path=path, method=request.method)
        body = (
            '{"detail":"maintenance",'
            f'"message":{message!r},'
            '"code":"maintenance_mode"}'
        ).replace("'", '"')
        return Response(
            content=body,
            status_code=503,
            media_type="application/json",
            headers={"Retry-After": "60"},
        )
