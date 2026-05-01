# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Personal Access Token authentication middleware.

Sits in the middleware chain *after* maintenance / rate-limit /
captcha but *before* the cookie-auth dep chain. When a request
carries an ``Authorization: Bearer atr_pat_…`` header, this
middleware:

1. Validates the wire format (cheap CRC check, no DB).
2. Looks up candidate rows by the 12-char public prefix.
3. argon2-verifies each candidate (almost always exactly one).
4. Checks ``revoked_at``, ``expires_at``, and ``user.is_active``.
5. Computes ``scopes ∩ user.permissions`` — a token can never do
   what its user cannot.
6. Stashes a fully-formed ``Principal`` on the request scope and
   pins the token id on the audit ContextVar so downstream
   ``audit.record(...)`` calls land on the right token.
7. After the response, updates ``last_used_at`` / ip / ua /
   ``use_count`` with a fresh session (the request session is
   already closed by then).

PATs do **not** bypass maintenance mode — when the kill switch
is on, programmatic callers see the same 503 as cookie callers.
The recovery path stays a super-admin's cookie session.

Tokens with no matching row, expired, revoked, or for an inactive
user all return ``401 invalid_token`` (or a more specific code) with
no body that distinguishes between them at the middleware boundary.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from fastapi import Request, Response
from sqlalchemy import select, update
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth.pat_format import (
    LOOKUP_PREFIX_LEN,
    PREFIX,
    validate_format,
)
from app.auth.pat_hashing import verify_token
from app.auth.principal import SCOPE_KEY, Principal
from app.auth.rbac import get_user_permissions
from app.db import get_session_factory
from app.logging import log
from app.models.auth import User
from app.models.auth_token import AuthToken
from app.services.audit import set_token_id

_BEARER_PREFIX: Final = "Bearer "


def _401(code: str, message: str | None = None) -> Response:
    body = (
        '{"detail":"unauthorized","code":' + _q(code) + (
            ',"message":' + _q(message) if message else ""
        ) + "}"
    )
    return Response(
        content=body,
        status_code=401,
        media_type="application/json",
    )


def _q(value: str) -> str:
    """Quote a value for inclusion in a hand-built JSON body. Keeps
    us off ``json.dumps`` for hot-path errors but still escapes the
    handful of chars that matter inside a string literal."""
    safe = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{safe}"'


async def _pats_enabled() -> bool:
    """Read ``app_settings['pats'].enabled``. Default-off; failure
    to read also returns False (closed-fail).

    Reading on every PAT-presenting request is fine: PATs are far
    rarer than cookie requests, and a 2-3 ms DB hit per PAT call is
    not the bottleneck. Don't add a process-wide cache without a
    good reason — the maintenance-cache TTL bug class is already
    noisy enough.
    """
    from app.services.app_config import get_namespace

    factory = get_session_factory()
    try:
        async with factory() as session:
            cfg = await get_namespace(session, "pats")
        return bool(getattr(cfg, "enabled", False))
    except Exception as exc:
        log.warning("pat.config_read_failed", error=str(exc))
        return False


class PATAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate ``Authorization: Bearer atr_pat_*`` requests."""

    async def dispatch(self, request: Request, call_next):
        auth_header = request.headers.get("authorization") or ""
        if not auth_header.startswith(_BEARER_PREFIX):
            return await call_next(request)

        token = auth_header[len(_BEARER_PREFIX):].strip()
        if not token.startswith(PREFIX):
            # Bearer header but not an atrium PAT — leave it for any
            # downstream auth handler. Today nothing else consumes
            # bearer tokens, but cookie auth doesn't care about the
            # header so falling through is harmless.
            return await call_next(request)

        if not validate_format(token):
            return _401("invalid_token", "Token format invalid.")

        if not await _pats_enabled():
            # Don't broadcast that PATs exist if the operator turned
            # them off — same posture as ``/auth/register`` returning
            # 404 when ``allow_signup`` is false.
            log.info("pat.disabled", path=request.url.path)
            return _401("invalid_token")

        prefix = token[:LOOKUP_PREFIX_LEN]
        factory = get_session_factory()
        async with factory() as db:
            # Prefix is 12 chars (8 fixed + 4 random base64url) =
            # ~16.7M distinct prefixes. Collisions are extremely
            # rare but not impossible at scale; ``.scalar()`` would
            # silently drop colliding rows. Fetch all candidates and
            # verify each. Almost always exactly one.
            candidates = (
                await db.scalars(
                    select(AuthToken).where(
                        AuthToken.token_prefix == prefix,
                        AuthToken.revoked_at.is_(None),
                    )
                )
            ).all()
            if not candidates:
                return _401("invalid_token")

            row = next(
                (c for c in candidates if verify_token(token, c.token_hash)),
                None,
            )
            if row is None:
                return _401("invalid_token")

            now = datetime.now(UTC).replace(tzinfo=None)
            if row.expires_at is not None and row.expires_at < now:
                return _401("token_expired")

            user = await db.get(User, row.user_id)
            if user is None or not user.is_active:
                return _401("user_inactive")

            user_permissions = await get_user_permissions(db, user.id)
            effective_scopes = frozenset(row.scopes or []) & user_permissions

            principal = Principal(
                user=user,
                permissions=effective_scopes,
                auth_method=(
                    "service_account_pat"
                    if user.is_service_account
                    else "pat"
                ),
                token_id=row.id,
                auth_session_id=None,
            )
            row_id = row.id

        # Pin the principal on the request scope so ``current_user``
        # and ``current_principal`` short-circuit; pin the token id
        # on the audit ContextVar so downstream ``record(...)`` calls
        # attribute to the issuing token.
        request.scope[SCOPE_KEY] = principal
        set_token_id(row_id)
        try:
            response = await call_next(request)
        finally:
            # Always clear so the contextvar can't leak into a
            # subsequent request handled by the same task.
            set_token_id(None)

        # last_used_at writeback: fresh session because the one above
        # is closed; running after the response so the request itself
        # never blocks on the UPDATE. Best-effort — a failure here
        # mustn't propagate as a 500 to the caller (the request has
        # already finished successfully).
        try:
            async with factory() as db2:
                await db2.execute(
                    update(AuthToken)
                    .where(AuthToken.id == row_id)
                    .values(
                        last_used_at=datetime.now(UTC).replace(tzinfo=None),
                        last_used_ip=(
                            request.client.host if request.client else None
                        ),
                        last_used_user_agent=request.headers.get("user-agent"),
                        use_count=AuthToken.use_count + 1,
                    )
                )
                await db2.commit()
        except Exception as exc:
            log.warning("pat.last_used_writeback_failed", error=str(exc))

        return response
