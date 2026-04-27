# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Extended /users/me payload.

fastapi-users' built-in /users/me returns a UserRead. This sibling
endpoint adds the runtime RBAC context the frontend needs:

- ``permissions``: every permission code the current user holds (used
  to gate UI controls like the Impersonate button)
- ``impersonating_from``: the original user when the active session is
  an impersonation, so the UI can render a "viewing as …" banner

It's a separate endpoint (instead of extending UserRead) to avoid
shadowing the fastapi-users schema and to keep /users/me cachable at
its existing shape.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.impersonate import IMPERSONATOR_COOKIE, _read_impersonator
from app.auth.rbac import get_user_permissions
from app.auth.users import current_user
from app.db import get_session
from app.models.auth import User
from app.models.rbac import Role, user_roles

router = APIRouter(prefix="/users/me", tags=["users"])


class ImpersonatorInfo(BaseModel):
    id: int
    email: str
    full_name: str


class MeContext(BaseModel):
    id: int
    email: str
    full_name: str
    roles: list[str]
    is_active: bool
    permissions: list[str]
    impersonating_from: ImpersonatorInfo | None = None


@router.get("/context", response_model=MeContext)
async def get_me_context(
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> MeContext:
    perms = sorted(await get_user_permissions(session, user.id))
    role_codes = sorted(
        (
            await session.execute(
                select(Role.code)
                .join(user_roles, user_roles.c.role_id == Role.id)
                .where(user_roles.c.user_id == user.id)
            )
        ).scalars().all()
    )

    impersonating_from: ImpersonatorInfo | None = None
    token = request.cookies.get(IMPERSONATOR_COOKIE)
    if token:
        try:
            actor_id = _read_impersonator(token)
        except Exception:
            # Stale or tampered cookie — ignore rather than fail the
            # whole request; the UI will treat the session as normal.
            actor_id = None
        if actor_id is not None:
            actor = await session.get(User, actor_id)
            if actor is not None:
                impersonating_from = ImpersonatorInfo(
                    id=actor.id, email=actor.email, full_name=actor.full_name
                )

    return MeContext(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        roles=role_codes,
        is_active=user.is_active,
        permissions=perms,
        impersonating_from=impersonating_from,
    )
