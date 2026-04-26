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

    Partial sessions (post-password, pre-TOTP-verify) trip a 403 with
    ``code=totp_required`` so the frontend routes to the challenge
    screen. We look the session row up via the ``sid`` claim on the
    cookie — which the strategy has already verified — rather than
    trying to thread the row through from the strategy.
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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "totp_required"},
        )
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
