# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""User impersonation — "log in as another user" for testing.

Gated on the ``user.impersonate`` permission (carried by the
``super_admin`` system role). A plain owner cannot impersonate.

Session mechanics: a successful POST swaps the ``atrium_auth`` cookie
(the fastapi-users JWT) for one minted against the target user, and
sets a second signed cookie ``atrium_impersonator`` carrying the actor's
own id so they can stop impersonating and return to themselves.

Guards:
- can't impersonate yourself
- target must be active
- target must NOT hold ``user.impersonate`` — no super-admin laundering,
  no circular impersonation

Every start and stop is audit-logged.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi_users.jwt import decode_jwt, generate_jwt
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.backend import DBSessionJWTStrategy, auth_backend
from app.auth.manager import UserManager, get_user_manager
from app.auth.rbac import get_user_permissions, require_perm
from app.auth.users import current_user
from app.db import get_session
from app.models.auth import User
from app.models.auth_session import AuthSession
from app.services.audit import record as record_audit
from app.settings import get_settings

router = APIRouter(prefix="/admin", tags=["admin"])

# Name is distinct from the fastapi-users cookie so the browser sends
# both on every request. Audience scopes the JWT so it can't be
# accidentally accepted as a regular auth token.
IMPERSONATOR_COOKIE = "atrium_impersonator"
IMPERSONATOR_AUDIENCE = ["atrium:impersonator"]


def _impersonator_ttl() -> int:
    # Match the auth cookie — when the auth JWT expires the user has
    # to re-authenticate anyway, at which point they're back to
    # themselves.
    return get_settings().jwt_access_token_expire_minutes * 60


def _sign_impersonator(actor_user_id: int) -> str:
    return generate_jwt(
        data={"sub": str(actor_user_id), "aud": IMPERSONATOR_AUDIENCE},
        secret=get_settings().jwt_secret,
        lifetime_seconds=_impersonator_ttl(),
    )


def _read_impersonator(token: str) -> int:
    data = decode_jwt(
        token,
        secret=get_settings().jwt_secret,
        audience=IMPERSONATOR_AUDIENCE,
    )
    return int(data["sub"])


def _set_impersonator_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=IMPERSONATOR_COOKIE,
        value=token,
        max_age=_impersonator_ttl(),
        httponly=True,
        samesite="lax",
        secure=settings.environment == "prod",
    )


def _clear_impersonator_cookie(response: Response) -> None:
    # Match the attributes used on set so the browser actually
    # invalidates the prior cookie.
    settings = get_settings()
    response.delete_cookie(
        key=IMPERSONATOR_COOKIE,
        httponly=True,
        samesite="lax",
        secure=settings.environment == "prod",
    )


async def _issue_auth_cookie_for(
    response: Response,
    user: User,
    user_manager: UserManager,
    session: AsyncSession,
    *,
    skip_2fa: bool = False,
) -> None:
    """Mint a JWT for ``user`` and set it as the auth cookie via the
    configured backend. We borrow the real backend's login() helper so
    cookie name/flags stay in sync with the login endpoint.

    ``skip_2fa=True`` flips the just-minted auth_session row's
    ``totp_passed=True`` so the caller doesn't bounce through /2fa.
    Only safe for impersonation: the actor's own session is already
    fully authenticated (the endpoints live behind ``current_user`` /
    ``require_perm``), and the impersonator cookie pins identity for
    the /stop round-trip — re-challenging 2FA inside a single trust
    boundary just annoys the actor.

    The strategy is constructed inline (instead of via
    ``auth_backend.get_strategy``) because that callable is a FastAPI
    dependency that needs a session injected — outside a Depends chain
    we pass it explicitly.
    """
    settings = get_settings()
    strategy = DBSessionJWTStrategy(
        session=session,
        secret=settings.jwt_secret,
        lifetime_seconds=settings.jwt_access_token_expire_minutes * 60,
    )
    token = await strategy.write_token(user)

    if skip_2fa:
        decoded = decode_jwt(
            token,
            secret=settings.jwt_secret,
            audience=strategy.token_audience,
        )
        await session.execute(
            update(AuthSession)
            .where(AuthSession.session_id == decoded["sid"])
            .values(totp_passed=True)
        )
        await session.commit()

    login_response = await auth_backend.transport.get_login_response(token)
    for key, value in login_response.headers.items():
        if key.lower() == "set-cookie":
            response.headers.append("set-cookie", value)


@router.post("/users/{user_id}/impersonate", status_code=status.HTTP_200_OK)
async def start_impersonation(
    user_id: int,
    response: Response,
    actor: User = Depends(require_perm("user.impersonate")),
    session: AsyncSession = Depends(get_session),
    user_manager: UserManager = Depends(get_user_manager),
) -> dict:
    if actor.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="you can't impersonate yourself",
        )

    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if not target.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="target user is inactive",
        )

    target_perms = await get_user_permissions(session, target.id)
    if "user.impersonate" in target_perms:
        # Forbidden rather than a softer error — this is the critical
        # guard that keeps impersonation from being a privilege-
        # escalation primitive.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="cannot impersonate another super admin",
        )

    await record_audit(
        session,
        actor_user_id=actor.id,
        entity="user",
        entity_id=target.id,
        action="impersonate_start",
        diff={"target_email": target.email},
    )
    await session.commit()

    await _issue_auth_cookie_for(
        response, target, user_manager, session, skip_2fa=True
    )
    _set_impersonator_cookie(response, _sign_impersonator(actor.id))
    return {
        "id": target.id,
        "email": target.email,
        "full_name": target.full_name,
    }


@router.post("/impersonate/stop", status_code=status.HTTP_200_OK)
async def stop_impersonation(
    request: Request,
    response: Response,
    current: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    user_manager: UserManager = Depends(get_user_manager),
) -> dict:
    token = request.cookies.get(IMPERSONATOR_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="not currently impersonating",
        )
    try:
        actor_id = _read_impersonator(token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="impersonation cookie invalid or expired",
        ) from exc

    actor = await session.get(User, actor_id)
    if actor is None or not actor.is_active:
        _clear_impersonator_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="original user is no longer available",
        )

    await record_audit(
        session,
        actor_user_id=actor.id,
        entity="user",
        entity_id=current.id,
        action="impersonate_stop",
        diff={"target_email": current.email},
    )
    await session.commit()

    await _issue_auth_cookie_for(
        response, actor, user_manager, session, skip_2fa=True
    )
    _clear_impersonator_cookie(response)
    return {"id": actor.id, "email": actor.email, "full_name": actor.full_name}
