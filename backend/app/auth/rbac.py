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
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    """
    result = await session.execute(
        select(role_permissions.c.permission_code)
        .select_from(user_roles)
        .join(role_permissions, role_permissions.c.role_id == user_roles.c.role_id)
        .where(user_roles.c.user_id == user_id)
        .distinct()
    )
    return {row[0] for row in result.all()}


def require_perm(code: str):
    """Dependency factory: 403 unless the current user has ``code``."""

    async def _dep(
        user: User = Depends(current_user),
        session: AsyncSession = Depends(get_session),
    ) -> User:
        perms = await get_user_permissions(session, user.id)
        if code not in perms:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"permission '{code}' required",
            )
        return user

    return _dep


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
