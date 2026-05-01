# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Permission resolver + FastAPI dependencies for RBAC checks.

The effective permission set for a user is the union over every role
assigned to them. Roles and permissions live in ``app.models.rbac``;
seed data lives in migration 0007.

Usage:

    @router.get("/seasons")
    async def list_seasons(
        _u: User = Depends(require_perm("season.read")),
    ):
        ...

``require_admin`` in ``app.auth.users`` is a convenience that checks
for the ``admin`` RBAC role. Prefer ``require_perm`` for finer-grained
gates so future roles compose cleanly.

``current_principal`` and ``require_pat_scope`` live here too —
they're tightly coupled to ``require_perm`` and keeping the trio
in one module avoids the import cycle (``principal`` is a leaf with
just the dataclass + ``SCOPE_KEY``).
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import SCOPE_KEY, Principal
from app.auth.users import current_user
from app.db import get_session
from app.models.auth import User
from app.models.rbac import Role, role_permissions, user_roles


async def get_user_permissions(
    session: AsyncSession, user_id: int
) -> set[str]:
    """Return the union of permission codes granted to ``user_id``.

    One query, joined through user_roles → role_permissions. Empty set
    if the user has no roles (which shouldn't happen in practice).

    Prefer ``current_user_permissions`` from a route — it resolves once
    per request via FastAPI's dep cache, so multiple ``require_perm``
    gates on the same endpoint don't re-query.
    """
    result = await session.execute(
        select(role_permissions.c.permission_code)
        .select_from(user_roles)
        .join(role_permissions, role_permissions.c.role_id == user_roles.c.role_id)
        .where(user_roles.c.user_id == user_id)
        .distinct()
    )
    return {row[0] for row in result.all()}


async def current_user_permissions(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> set[str]:
    """Effective permission set for the current user, cached per request.

    FastAPI memoises a ``Depends`` by callable identity within a single
    request, so any number of ``require_perm("...")`` gates on one
    endpoint resolve to a single ``get_user_permissions`` call. Host
    code that needs the full set (e.g. to render a UI gate server-side
    or branch on a non-fatal capability) should depend on this rather
    than calling ``get_user_permissions`` directly.
    """
    return await get_user_permissions(session, user.id)


async def current_principal(
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Principal:
    """Resolve the principal for this request.

    Two paths:

    1. **PAT** — ``PATAuthMiddleware`` already authenticated the
       bearer, intersected scopes with the user's current
       permissions, and stashed a fully-formed ``Principal`` in
       the scope slot. ``current_user`` short-circuits on the same
       slot (returning the PAT user without the cookie / TOTP
       gates), so by the time we run, ``user`` is the PAT user and
       the scope slot still holds the pre-built principal — we
       hand it back directly to preserve the scope-intersection
       semantics.
    2. **Cookie** — ``current_user`` enforced the totp + 2FA-
       enrollment gates as usual. Resolve the user's full
       permission set and wrap in a Principal for the caller.
    """
    pat_principal = request.scope.get(SCOPE_KEY)
    if pat_principal is not None and isinstance(pat_principal, Principal):
        # Re-use the middleware-built principal so PAT scope
        # intersection wins over the user's full permission set.
        return pat_principal

    permissions = await get_user_permissions(session, user.id)
    return Principal(
        user=user,
        permissions=frozenset(permissions),
        auth_method="password",
        token_id=None,
        auth_session_id=_sid_from_request(request),
    )


def _sid_from_request(request: Request) -> str | None:
    """Best-effort decode of the ``sid`` claim from the auth cookie.

    Mirrors ``app.auth.users._sid_from_cookie`` but lives here so
    ``current_principal`` doesn't need to reach into ``users``
    twice (once via Depends, once for the helper).
    """
    import jwt as pyjwt

    token = request.cookies.get("atrium_auth")
    if not token:
        return None
    try:
        data = pyjwt.decode(token, options={"verify_signature": False})
        sid = data.get("sid")
        return sid if isinstance(sid, str) else None
    except Exception:
        return None


def require_perm(code: str):
    """Dependency factory: 403 unless the current principal has ``code``.

    Resolves through ``current_principal`` so PAT-authed and
    cookie-authed requests share one gate. ``permissions`` for a
    PAT request is the intersection of the token's scopes and the
    user's current permissions; for a cookie request it's the
    user's full permission set.

    Returns the ``User`` so the existing call-site contract
    (``_u: User = Depends(require_perm("..."))``) keeps working.
    Routes that need the auth method or token id can depend on
    ``current_principal`` directly.
    """

    async def _dep(
        principal: Principal = Depends(current_principal),
    ) -> User:
        if code not in principal.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"permission '{code}' required",
            )
        return principal.user

    return _dep


def require_pat_scope(*scopes: str):
    """Convenience factory for routes reachable *only* via a PAT
    carrying one of the given scopes (PAT-management endpoints,
    typically). Refuses cookie-authed requests with ``pat_required``.

    Most routes should use ``require_perm(...)``. Reach for this
    only when you need to refuse cookie auth explicitly.
    """

    async def _dep(principal: Principal = Depends(current_principal)) -> Principal:
        if principal.auth_method == "password":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "pat_required"},
            )
        if not any(scope in principal.permissions for scope in scopes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "insufficient_scope"},
            )
        return principal

    return _dep


async def require_cookie_auth(
    principal: Principal = Depends(current_principal),
) -> User:
    """Refuse PAT-authenticated callers.

    Add this alongside ``require_perm("...")`` on every PAT-management
    route. A PAT must not be able to mint, revoke, or rotate other PATs
    even if it (somehow) carries ``auth.pats.admin_revoke`` — the
    issuance and revocation surface stays cookie-only so a leaked PAT
    cannot bootstrap further tokens.

    Doubles as the v1 step-up gate: ``current_user`` already enforces
    ``auth_sessions.totp_passed=True`` on cookie callers, so any
    request that reaches this dep has both a cookie *and* a full 2FA-
    completed session. A real fresh-challenge primitive is descoped per
    spec §13 — wire this here when one lands.
    """
    if principal.auth_method != "password":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "cookie_auth_required"},
        )
    return principal.user


async def assign_role(
    session: AsyncSession, *, user_id: int, role_code: str
) -> None:
    """Grant a role to a user. Idempotent — inserts are no-ops if the
    link already exists (MySQL ON DUPLICATE KEY UPDATE)."""
    role_id = (
        await session.execute(select(Role.id).where(Role.code == role_code))
    ).scalar_one()
    await session.execute(
        user_roles.insert().prefix_with("IGNORE").values(
            user_id=user_id, role_id=role_id
        )
    )
