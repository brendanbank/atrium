# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Role + permission administration (gated by ``role.manage``).

Permissions are a fixed, code-defined catalogue seeded via migrations —
this router only lets an admin list them. Roles are read/write: an
admin can create a new role, rename an existing one, toggle its
permissions, and delete non-system roles.

System roles (``is_system=True``) can have their permissions edited
(that's the whole point of this admin UI) but can't be renamed or
deleted — they're the identity anchors for the RBAC checks and
invite flows.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import require_perm
from app.db import get_session
from app.models.auth import User
from app.models.rbac import Permission, Role, role_permissions
from app.services.audit import record as record_audit

router = APIRouter(tags=["admin"])


class PermissionRead(BaseModel):
    code: str
    description: str | None

    model_config = {"from_attributes": True}


class RoleRead(BaseModel):
    id: int
    code: str
    name: str
    is_system: bool
    permissions: list[str]  # permission codes

    model_config = {"from_attributes": True}


class RoleCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=100)
    permissions: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    permissions: list[str] | None = None


def _role_to_read(role: Role) -> RoleRead:
    return RoleRead(
        id=role.id,
        code=role.code,
        name=role.name,
        is_system=role.is_system,
        permissions=sorted(p.code for p in role.permissions),
    )


async def _validate_permissions(
    session: AsyncSession, codes: list[str]
) -> None:
    """Reject role writes that reference unknown permission codes."""
    if not codes:
        return
    rows = (
        await session.execute(
            select(Permission.code).where(Permission.code.in_(codes))
        )
    ).scalars().all()
    missing = set(codes) - set(rows)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown permission codes: {sorted(missing)}",
        )


@router.get("/admin/permissions", response_model=list[PermissionRead])
async def list_permissions(
    _actor: User = Depends(require_perm("role.manage")),
    session: AsyncSession = Depends(get_session),
) -> list[Permission]:
    rows = await session.execute(select(Permission).order_by(Permission.code))
    return list(rows.scalars().all())


@router.get("/admin/roles", response_model=list[RoleRead])
async def list_roles(
    _actor: User = Depends(require_perm("role.manage")),
    session: AsyncSession = Depends(get_session),
) -> list[RoleRead]:
    # selectin for permissions lands on Role via the relationship's
    # default lazy mode (we set lazy='selectin' in the model).
    rows = (
        await session.execute(select(Role).order_by(Role.code))
    ).scalars().all()
    return [_role_to_read(r) for r in rows]


@router.post("/admin/roles", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
async def create_role(
    payload: RoleCreate,
    owner: User = Depends(require_perm("role.manage")),
    session: AsyncSession = Depends(get_session),
) -> RoleRead:
    clash = (
        await session.execute(select(Role).where(Role.code == payload.code))
    ).scalar_one_or_none()
    if clash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"a role with code '{payload.code}' already exists",
        )
    await _validate_permissions(session, payload.permissions)

    role = Role(code=payload.code, name=payload.name, is_system=False)
    session.add(role)
    await session.flush()

    for code in payload.permissions:
        await session.execute(
            role_permissions.insert().values(
                role_id=role.id, permission_code=code
            )
        )

    await record_audit(
        session,
        actor_user_id=owner.id,
        entity="role",
        entity_id=role.id,
        action="create",
        diff={
            "code": role.code,
            "name": role.name,
            "permissions": sorted(payload.permissions),
        },
    )
    await session.commit()
    await session.refresh(role)
    return _role_to_read(role)


@router.patch("/admin/roles/{role_id}", response_model=RoleRead)
async def update_role(
    role_id: int,
    payload: RoleUpdate,
    owner: User = Depends(require_perm("role.manage")),
    session: AsyncSession = Depends(get_session),
) -> RoleRead:
    role = await session.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    # System roles keep their name (it's semantic — renaming "Owner"
    # would confuse every future migration author). Permissions are
    # free to change.
    if role.is_system and payload.name is not None and payload.name != role.name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot rename a system role",
        )

    diff: dict = {}
    if payload.name is not None and payload.name != role.name:
        diff["name"] = {"from": role.name, "to": payload.name}
        role.name = payload.name

    if payload.permissions is not None:
        await _validate_permissions(session, payload.permissions)
        current = {p.code for p in role.permissions}
        desired = set(payload.permissions)
        added = desired - current
        removed = current - desired

        if added:
            await session.execute(
                role_permissions.insert(),
                [
                    {"role_id": role.id, "permission_code": c}
                    for c in sorted(added)
                ],
            )
        if removed:
            await session.execute(
                delete(role_permissions).where(
                    role_permissions.c.role_id == role.id,
                    role_permissions.c.permission_code.in_(removed),
                )
            )
        if added or removed:
            diff["permissions"] = {
                "added": sorted(added),
                "removed": sorted(removed),
            }

    if diff:
        await record_audit(
            session,
            actor_user_id=owner.id,
            entity="role",
            entity_id=role.id,
            action="update",
            diff=diff,
        )

    await session.commit()
    # Re-fetch so relationship reflects the just-committed membership.
    await session.refresh(role)
    return _role_to_read(role)


@router.delete("/admin/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: int,
    owner: User = Depends(require_perm("role.manage")),
    session: AsyncSession = Depends(get_session),
) -> None:
    role = await session.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot delete a system role",
        )

    await record_audit(
        session,
        actor_user_id=owner.id,
        entity="role",
        entity_id=role.id,
        action="delete",
        diff={"code": role.code, "name": role.name},
    )
    # user_roles + role_permissions cascade via FK — any users holding
    # the role simply lose it (not deactivated).
    await session.delete(role)
    await session.commit()
