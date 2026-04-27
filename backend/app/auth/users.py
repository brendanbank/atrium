# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""FastAPIUsers singleton + dependency helpers.

Two tiers of "authenticated":

- ``current_user_partial`` — the base fastapi-users dep. Used only by
  endpoints that must remain reachable during TOTP enrollment /
  challenge: ``/auth/totp/*`` and the fastapi-users-supplied
  ``/users/me``. No other code should import this.
- ``current_user`` — wraps the partial dep and additionally requires
  ``auth_sessions.totp_passed=True``. Every domain endpoint uses this.

For permission gates use ``app.auth.rbac.require_perm("…")``. The
``require_admin`` shortcut here is a convenience for routes that just
want "any user with the admin role" without naming a specific
permission.
"""
from fastapi import Depends, HTTPException, Request, status
from fastapi_users import FastAPIUsers
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.backend import auth_backend
from app.auth.manager import get_user_manager
from app.auth.two_factor import (
    user_has_any_2fa,
    user_has_enforced_role,
)
from app.db import get_session
from app.models.auth import User
from app.models.auth_session import AuthSession
from app.models.rbac import Role, user_roles

fastapi_users = FastAPIUsers[User, int](get_user_manager, [auth_backend])

# Base dep — does NOT enforce the TOTP gate. Exported for endpoints
# that must work during enrollment / challenge.
current_user_partial = fastapi_users.current_user(active=True)

ADMIN_ROLE_CODE = "admin"


def _sid_from_cookie(request: Request) -> str | None:
    import jwt as pyjwt

    token = request.cookies.get("atrium_auth")
    if not token:
        return None
    try:
        data = pyjwt.decode(token, options={"verify_signature": False})
        return data.get("sid")
    except Exception:
        return None


async def current_user(
    request: Request,
    user: User = Depends(current_user_partial),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Authenticated user + passed-TOTP gate. Default for all domain
    endpoints.

    Partial sessions (post-password, pre-TOTP-verify) trip a 403. The
    detail ``code`` distinguishes two states the frontend handles
    differently:

    - ``totp_required`` — user has confirmed a 2FA method, frontend
      shows the challenge screen at /2fa.
    - ``2fa_enrollment_required`` — user holds a role listed in
      ``auth.require_2fa_for_roles`` but has no confirmed 2FA factor.
      Frontend routes to the same /2fa page (which already shows the
      setup picker for unenrolled users) but the distinct code lets
      the UI surface a clearer "your account requires 2FA" hint.

    Note: with the opt-in 2FA gating, login already grants
    ``totp_passed=True`` for users with no factor and no enforced role,
    so the partial-session path here only fires for users who actually
    need to challenge or enrol.
    """
    sid = _sid_from_cookie(request)
    if sid is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    row = (
        await session.execute(
            select(AuthSession).where(AuthSession.session_id == sid)
        )
    ).scalar_one_or_none()
    if row is None or not row.totp_passed:
        # Default code preserves the pre-Phase-3 behaviour. The
        # enrollment-required variant only kicks in when the user has
        # zero 2FA factors AND at least one of their roles is on the
        # enforcement list — otherwise we'd show the setup picker to
        # users who'd rather log in without 2FA.
        code = "totp_required"
        try:
            from app.services.app_config import AuthConfig, get_namespace

            cfg = await get_namespace(session, "auth")
            if (
                isinstance(cfg, AuthConfig)
                and cfg.require_2fa_for_roles
                and not await user_has_any_2fa(session, user.id)
                and await user_has_enforced_role(
                    session, user.id, cfg.require_2fa_for_roles
                )
            ):
                code = "2fa_enrollment_required"
        except Exception:
            # Don't let an auth-config read failure mask the underlying
            # 403 — fall back to the generic code.
            pass
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": code},
        )
    # Even on a full session, an enforcement role added after the user
    # last logged in (or the toggle flipped on) means we must refuse
    # until they enroll. A user who's already passed 2FA on this
    # session has, by definition, a confirmed factor — but a
    # super_admin admin reset could wipe their factors mid-session, so
    # we still re-check here.
    try:
        from app.services.app_config import AuthConfig, get_namespace

        cfg = await get_namespace(session, "auth")
        if (
            isinstance(cfg, AuthConfig)
            and cfg.require_2fa_for_roles
            and not await user_has_any_2fa(session, user.id)
            and await user_has_enforced_role(
                session, user.id, cfg.require_2fa_for_roles
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "2fa_enrollment_required"},
            )
    except HTTPException:
        raise
    except Exception:
        pass
    return user


async def require_admin(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Convenience gate for "must hold the admin role".

    For finer-grained checks use ``require_perm("…")`` from
    ``app.auth.rbac`` — that's the preferred pattern.
    """
    has_admin = (
        await session.execute(
            select(user_roles.c.user_id)
            .join(Role, Role.id == user_roles.c.role_id)
            .where(
                user_roles.c.user_id == user.id,
                Role.code == ADMIN_ROLE_CODE,
            )
        )
    ).first()
    if not has_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin role required",
        )
    return user
