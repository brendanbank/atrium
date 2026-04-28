# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Owner-only user administration.

fastapi-users ships a /users/{id} router but its authz is gated on
``is_superuser`` (a column we've dropped — authority flows through the
``super_admin`` RBAC role). Rather than conflate role and flag, this
router exposes just what the admin UI needs:

- GET  /admin/users         list every account
- PATCH /admin/users/{id}   update role / active flag

Password reset is still done via the standard ``/auth/forgot-password``
flow; this router does not touch passwords.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.manager import UserManager, get_user_manager
from app.auth.rbac import get_user_permissions, require_perm
from app.auth.schemas import UserRead
from app.db import get_session
from app.logging import log
from app.models.auth import User, UserInvite
from app.models.rbac import Role, user_roles
from app.services.audit import record as record_audit

router = APIRouter(prefix="/admin/users", tags=["admin"])


class UserAdminUpdate(BaseModel):
    is_active: bool | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = None
    # Replace the user's RBAC roles with exactly this set (by id). None
    # leaves the existing roles alone; an empty list strips them all.
    role_ids: list[int] | None = None


class UserAdminRead(UserRead):
    """Admin list/detail view: standard UserRead + RBAC role ids and codes.

    ``roles`` carries the stable string codes (``"admin"``, ``"super_admin"``,
    host-defined codes etc.); ``role_ids`` carries the per-environment
    integer ids. Hosts that filter users by role membership ("show me
    everyone without the agent role") read ``roles`` and avoid a
    second ``/admin/roles`` lookup; the patch endpoint still expects
    ``role_ids`` since ids are what the MultiSelect in the admin UI
    binds to.
    """

    role_ids: list[int] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)


async def _roles_for(
    session: AsyncSession, user_id: int
) -> tuple[list[int], list[str]]:
    """Return ``(role_ids, role_codes)`` for ``user_id`` from a single
    join query. Both lists are sorted: ids ascending numerically, codes
    ascending lexicographically. Codes are sorted independently so the
    two lists are not positionally aligned — the consumer treats each
    as a set, not an array of pairs."""
    rows = (
        await session.execute(
            select(Role.id, Role.code)
            .join(user_roles, user_roles.c.role_id == Role.id)
            .where(user_roles.c.user_id == user_id)
        )
    ).all()
    ids = sorted(int(r[0]) for r in rows)
    codes = sorted(str(r[1]) for r in rows)
    return ids, codes


async def _role_ids_for(session: AsyncSession, user_id: int) -> list[int]:
    ids, _ = await _roles_for(session, user_id)
    return ids


async def _to_admin_read(session: AsyncSession, user: User) -> UserAdminRead:
    data = UserRead.model_validate(user, from_attributes=True).model_dump()
    role_ids, role_codes = await _roles_for(session, user.id)
    data["role_ids"] = role_ids
    data["roles"] = role_codes
    return UserAdminRead.model_validate(data)


@router.get("", response_model=list[UserAdminRead])
async def list_users(
    _actor: User = Depends(require_perm("user.manage")),
    session: AsyncSession = Depends(get_session),
) -> list[UserAdminRead]:
    users = list(
        (
            await session.execute(
                select(User).order_by(User.created_at.desc())
            )
        ).scalars().all()
    )
    return [await _to_admin_read(session, u) for u in users]


@router.patch("/{user_id}", response_model=UserAdminRead)
async def update_user(
    user_id: int,
    payload: UserAdminUpdate,
    owner: User = Depends(require_perm("user.manage")),
    session: AsyncSession = Depends(get_session),
) -> UserAdminRead:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    # Guardrail: don't let an admin lock themselves out.
    if target.id == owner.id and payload.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="you cannot deactivate your own account",
        )

    diff: dict = {}
    if payload.is_active is not None and payload.is_active != target.is_active:
        diff["is_active"] = {"from": target.is_active, "to": payload.is_active}
        target.is_active = payload.is_active
    if payload.full_name is not None and payload.full_name != target.full_name:
        diff["full_name"] = {"from": target.full_name, "to": payload.full_name}
        target.full_name = payload.full_name
    if payload.email is not None and payload.email != target.email:
        # Enforce uniqueness application-side so we can return a clean
        # 409 instead of bubbling an IntegrityError.
        clash = (
            await session.execute(
                select(User.id).where(
                    User.email == payload.email, User.id != target.id
                )
            )
        ).scalar_one_or_none()
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="a user with this email already exists",
            )
        diff["email"] = {"from": target.email, "to": payload.email}
        target.email = payload.email

    if payload.role_ids is not None:
        current = set(await _role_ids_for(session, target.id))
        desired = set(payload.role_ids)
        if desired != current:
            existing_ids = set(
                (
                    await session.execute(
                        select(Role.id).where(Role.id.in_(desired))
                    )
                ).scalars().all()
            )
            missing = desired - existing_ids
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"unknown role ids: {sorted(missing)}",
                )

            from app.models.rbac import role_permissions as rp

            # Privilege-escalation guard: an actor can only grant a
            # role whose permissions are a subset of their own. Without
            # this, a plain owner could self-promote to super_admin by
            # ticking the box.
            to_add = desired - current
            if to_add:
                actor_perms = await get_user_permissions(session, owner.id)
                role_perm_rows = (
                    await session.execute(
                        select(rp.c.role_id, rp.c.permission_code).where(
                            rp.c.role_id.in_(to_add)
                        )
                    )
                ).all()
                role_perms: dict[int, set[str]] = {}
                for rid, code in role_perm_rows:
                    role_perms.setdefault(rid, set()).add(code)
                for rid in to_add:
                    needed = role_perms.get(rid, set())
                    missing_perms = needed - actor_perms
                    if missing_perms:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail=(
                                "cannot grant a role whose permissions you "
                                f"don't hold: missing {sorted(missing_perms)}"
                            ),
                        )

            # Self-edit guard: don't strip the permissions that keep
            # this admin surface usable for the actor.
            if target.id == owner.id:
                granted = set(
                    (
                        await session.execute(
                            select(rp.c.permission_code).where(
                                rp.c.role_id.in_(desired)
                            )
                        )
                    ).scalars().all()
                )
                if "user.manage" not in granted:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="cannot remove your own user.manage permission",
                    )

            to_remove = current - desired
            if to_remove:
                await session.execute(
                    delete(user_roles).where(
                        user_roles.c.user_id == target.id,
                        user_roles.c.role_id.in_(to_remove),
                    )
                )
            if to_add:
                await session.execute(
                    user_roles.insert(),
                    [
                        {"user_id": target.id, "role_id": r}
                        for r in sorted(to_add)
                    ],
                )
            diff["role_ids"] = {
                "from": sorted(current),
                "to": sorted(desired),
            }

    if diff:
        await record_audit(
            session,
            actor_user_id=owner.id,
            entity="user",
            entity_id=target.id,
            action="update",
            diff=diff,
        )

    await session.commit()
    await session.refresh(target)
    return await _to_admin_read(session, target)


@router.post("/{user_id}/password-reset", status_code=status.HTTP_202_ACCEPTED)
async def admin_trigger_password_reset(
    user_id: int,
    owner: User = Depends(require_perm("user.manage")),
    session: AsyncSession = Depends(get_session),
    user_manager: UserManager = Depends(get_user_manager),
) -> dict[str, str]:
    """Owner-triggered password reset for another user.

    Issues the same signed token as /auth/forgot-password and sends the
    reset email via on_after_forgot_password. The admin never sees the
    token or the password — delivery is always through the target's
    email.
    """
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if not target.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot reset password for an inactive account",
        )

    await user_manager.forgot_password(target)

    # Second mail: tell the target *who* triggered the reset. The
    # reset link above goes out regardless; this notice is what turns
    # a silent "admin resets target's password and watches the inbox"
    # attack into something the target sees before the link is used.
    # Wrapped in try/except so an SMTP hiccup can't roll back the
    # audit row — the reset link is the primary action.
    from app.email.sender import send_and_log

    try:
        await send_and_log(
            session,
            template="admin_password_reset_notice",
            to=[target.email],
            context={
                "user": target,
                "admin": owner,
                "recipient": {
                    "email": target.email.lower(),
                    "full_name": target.full_name or "",
                },
            },
            locale=target.preferred_language or "en",
        )
    except Exception as exc:
        log.warning(
            "admin_password_reset.notice_email_failed",
            target_user_id=target.id,
            error=str(exc),
        )

    await record_audit(
        session,
        actor_user_id=owner.id,
        entity="user",
        entity_id=target.id,
        action="password_reset_triggered",
        diff={"email": target.email},
    )
    await session.commit()
    return {"detail": "reset email sent"}


@router.delete("/{user_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_permanent(
    user_id: int,
    owner: User = Depends(require_perm("user.manage")),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Hard-delete a user account.

    Guardrails:
      - can't delete self
      - can't delete anyone who issued invites (invited_by has RESTRICT)

    Cascades:
      - notifications: deleted (CASCADE)
      - audit_log.actor_user_id: set null (entries kept, actor anonymised)
    """
    if user_id == owner.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="you cannot delete your own account",
        )

    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    invite_count = (
        await session.execute(
            select(func.count(UserInvite.id)).where(
                UserInvite.invited_by_user_id == user_id
            )
        )
    ).scalar_one()
    if invite_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="user has issued invites; deactivate instead to keep history",
        )

    await record_audit(
        session,
        actor_user_id=owner.id,
        entity="user",
        entity_id=target.id,
        action="delete",
        diff={"email": target.email},
    )
    await session.delete(target)
    await session.commit()
