# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Unified request principal + ``current_principal`` dependency.

A ``Principal`` is the per-request answer to "who is making this
call and what can they do". It uniformly covers two auth methods:

- **password (cookie-authed)** — the user logged in interactively.
  ``permissions`` is the user's full effective permission set.
- **pat / service_account_pat** — the user authenticated via a
  Personal Access Token. ``permissions`` is the *intersection* of
  the token's stored scopes and the user's current permissions
  (computed in ``PATAuthMiddleware``), so a demoted user's tokens
  silently lose the matching scopes the next time they're used.

Why a side-channel through ``request.scope["principal"]`` rather
than threading it through fastapi-users? The cookie-auth chain
(``current_user`` + ``auth_sessions.totp_passed`` gate) is
purpose-built for cookie sessions. PATs are a parallel auth method
that doesn't have a cookie session at all. Forcing them through the
same dep chain would either duplicate the gate logic or paper over
it; instead the PAT middleware short-circuits and pre-populates the
slot, and ``current_principal`` reads from it before falling back
to cookie auth.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.users import current_user
from app.db import get_session
from app.models.auth import User

AuthMethod = Literal["password", "pat", "service_account_pat"]


@dataclass(frozen=True)
class Principal:
    """The answer to "who is calling and what can they do" for one
    request. Constructed once per request (or short-circuited from
    the PAT middleware's slot) and threaded through ``require_perm``.

    ``user`` is always present. ``permissions`` is already
    *effective* — for PATs it's the scope ∩ user-permissions
    intersection, not the raw stored scopes. ``token_id`` is set
    only for PAT requests; ``auth_session_id`` is set only for
    cookie requests (and even then it's optional — populated when
    the middleware decoded the cookie's ``sid``).
    """

    user: User
    permissions: frozenset[str]
    auth_method: AuthMethod
    token_id: int | None = None
    auth_session_id: str | None = None


# Sentinel key for the request scope slot that ``PATAuthMiddleware``
# populates and ``current_principal`` reads back. Using ``request.scope``
# (the ASGI dict) rather than ``request.state`` keeps PAT principal
# objects out of the broader Starlette-state surface and ensures clean
# isolation between requests handled by the same worker.
SCOPE_KEY = "atrium_principal"


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

    # Cookie path: build a Principal from the cookie-authed user
    # + their full permission set.
    from app.auth.rbac import get_user_permissions

    permissions = await get_user_permissions(session, user.id)
    return Principal(
        user=user,
        permissions=frozenset(permissions),
        auth_method="password",
        token_id=None,
        auth_session_id=_sid_from_request(request),
    )


def _sid_from_request(request: Request) -> str | None:
    """Best-effort decode of the ``sid`` claim from the auth cookie,
    matching ``app.auth.users._sid_from_cookie`` but kept private to
    this module so the cycle stays one-way."""
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


def require_pat_scope(*scopes: str):
    """Convenience factory for routes that should *only* be reachable
    via a PAT carrying one of the given scopes (i.e. routes the
    PAT-management UI calls — never reachable from a cookie session).

    Most routes should use ``require_perm(...)``. Reach for this
    only when you need to refuse cookie auth explicitly."""

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
