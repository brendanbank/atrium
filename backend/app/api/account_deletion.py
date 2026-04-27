# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Self-service + admin-driven account deletion.

Two endpoints:

* ``POST /users/me/delete`` — caller deletes their own account. Body
  is ``{"password": "..."}``; the password is verified before the
  deletion proceeds (defence in depth against an unattended-tab
  attacker). Returns 404 if ``auth.allow_self_delete`` is False so
  the absence of the route is indistinguishable from a route the
  operator hasn't enabled — useful for tenants that want admin-only
  offboarding.
* ``POST /admin/users/{id}/delete`` — gated on ``user.manage``. No
  password reconfirm (the admin already authenticated themselves).
  Refuses to delete a super_admin so the privilege-protection guard
  matches the impersonation rules.

Both paths funnel into ``services.account_deletion.soft_delete_user``
which anonymises PII, revokes auth sessions, schedules the hard
delete, and sends the confirmation email.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi_users.password import PasswordHelper
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import get_user_permissions, require_perm
from app.auth.users import current_user
from app.db import get_session
from app.models.auth import User
from app.services.account_deletion import soft_delete_user
from app.services.app_config import AuthConfig, get_namespace

self_router = APIRouter(prefix="/users/me", tags=["users"])
admin_router = APIRouter(prefix="/admin/users", tags=["admin"])

_password_helper = PasswordHelper()


class SelfDeleteRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


@self_router.post("/delete", status_code=status.HTTP_204_NO_CONTENT)
async def self_delete(
    body: SelfDeleteRequest,
    response: Response,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    auth_cfg = await get_namespace(session, "auth")
    assert isinstance(auth_cfg, AuthConfig)
    if not auth_cfg.allow_self_delete:
        # 404 rather than 403 so a tenant that disables self-deletion
        # doesn't broadcast the route's existence.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if user.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="account is already scheduled for deletion",
        )

    ok, _new_hash = _password_helper.verify_and_update(
        body.password, user.hashed_password
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    await soft_delete_user(
        session,
        user_id=user.id,
        actor_user_id=user.id,
        reason="self",
    )
    await session.commit()

    response.delete_cookie(
        key="atrium_auth",
        httponly=True,
        samesite="lax",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.post("/{user_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete(
    user_id: int,
    actor: User = Depends(require_perm("user.manage")),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if user_id == actor.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="use /users/me/delete to remove your own account",
        )

    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if target.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="account is already scheduled for deletion",
        )

    target_perms = await get_user_permissions(session, target.id)
    if "user.impersonate" in target_perms:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot delete a super_admin via this endpoint",
        )

    await soft_delete_user(
        session,
        user_id=target.id,
        actor_user_id=actor.id,
        reason="admin",
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
