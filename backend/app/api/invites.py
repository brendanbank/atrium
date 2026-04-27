# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Invite flow: owners create invites; recipients accept with a token
to set a password and activate their account.

No public signup — this is the only path by which new users are created.
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.manager import UserManager, get_user_manager
from app.auth.rbac import assign_role, require_perm
from app.auth.schemas import InviteAccept, InviteCreate, InviteCreated, InviteRead
from app.db import get_session
from app.email.sender import send_and_log
from app.logging import log
from app.models.auth import User, UserInvite
from app.services.audit import record as record_audit
from app.settings import get_settings

router = APIRouter(prefix="/invites", tags=["invites"])


def _issue_token() -> str:
    return secrets.token_urlsafe(48)


@router.post("", response_model=InviteCreated, status_code=status.HTTP_201_CREATED)
async def create_invite(
    payload: InviteCreate,
    owner: User = Depends(require_perm("user.manage")),
    session: AsyncSession = Depends(get_session),
) -> UserInvite:
    # Reject duplicate active invites for the same email
    existing = (
        await session.execute(
            select(UserInvite).where(
                UserInvite.email == payload.email,
                UserInvite.accepted_at.is_(None),
                UserInvite.revoked_at.is_(None),
                UserInvite.expires_at > datetime.now(UTC).replace(tzinfo=None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="an active invite already exists for this email",
        )

    # Reject if user already exists with that email
    existing_user = (
        await session.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="a user with this email already exists",
        )

    invite = UserInvite(
        token=_issue_token(),
        email=payload.email,
        full_name=payload.full_name,
        role_codes=payload.role_codes,
        invited_by_user_id=owner.id,
        expires_at=datetime.now(UTC).replace(tzinfo=None)
        + timedelta(hours=payload.expires_in_hours),
    )
    session.add(invite)
    await session.flush()
    await record_audit(
        session,
        actor_user_id=owner.id,
        entity="invite",
        entity_id=invite.id,
        action="create",
        diff={
            "email": invite.email,
            "role_codes": invite.role_codes,
            "full_name": invite.full_name,
            "expires_at": invite.expires_at.isoformat(),
        },
    )
    await session.commit()
    await session.refresh(invite)

    log.info(
        "invite.created",
        invite_id=invite.id,
        email=invite.email,
        role_codes=invite.role_codes,
        expires_at=invite.expires_at.isoformat(),
        token=invite.token,
    )

    # Deliver the acceptance link by email. Wrapped in try/except so a
    # broken SMTP config can't block invite creation — the UI still
    # surfaces the copyable link as a fallback.
    settings = get_settings()
    accept_url = (
        f"{settings.app_base_url.rstrip('/')}/accept-invite?token={invite.token}"
    )
    try:
        await send_and_log(
            session,
            template="invite",
            to=[invite.email],
            context={
                "invite": invite,
                "invited_by_name": owner.full_name,
                "accept_url": accept_url,
                "expires_on": invite.expires_at.strftime("%Y-%m-%d %H:%M UTC"),
                # Invitee hasn't accepted yet so we don't know their
                # real name — the template can still greet them by
                # email if it uses ``recipient.full_name``.
                "recipient": {
                    "email": invite.email.lower(),
                    "full_name": "",
                },
            },
            # Recipient has no preferred_language yet (they don't have
            # a User row) - use the inviter's so an admin in NL sends
            # Dutch invites by default. Falls back to EN when the
            # inviter has no preference set.
            locale=owner.preferred_language or "en",
        )
        await session.commit()
    except Exception as exc:
        log.warning(
            "invite.email_failed",
            invite_id=invite.id,
            email=invite.email,
            error=str(exc),
        )

    return invite


@router.get("", response_model=list[InviteRead])
async def list_invites(
    owner: User = Depends(require_perm("user.manage")),
    session: AsyncSession = Depends(get_session),
) -> list[UserInvite]:
    rows = await session.execute(
        select(UserInvite).order_by(UserInvite.created_at.desc())
    )
    return list(rows.scalars().all())


@router.delete("/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    invite_id: int,
    owner: User = Depends(require_perm("user.manage")),
    session: AsyncSession = Depends(get_session),
) -> None:
    invite = await session.get(UserInvite, invite_id)
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if invite.accepted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="invite already accepted",
        )
    invite.revoked_at = datetime.now(UTC).replace(tzinfo=None)
    await record_audit(
        session,
        actor_user_id=owner.id,
        entity="invite",
        entity_id=invite.id,
        action="revoke",
        diff={"email": invite.email, "role_codes": invite.role_codes},
    )
    await session.commit()


@router.post("/accept", status_code=status.HTTP_201_CREATED)
async def accept_invite(
    payload: InviteAccept,
    session: AsyncSession = Depends(get_session),
    user_manager: UserManager = Depends(get_user_manager),
) -> dict[str, int | str]:
    invite = (
        await session.execute(
            select(UserInvite).where(UserInvite.token == payload.token)
        )
    ).scalar_one_or_none()
    if invite is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="invite not found"
        )
    now = datetime.now(UTC).replace(tzinfo=None)
    if invite.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="invite revoked")
    if invite.accepted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="invite already accepted"
        )
    if invite.expires_at <= now:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="invite expired")

    # Create the user via the user manager so the password is hashed.
    from app.auth.schemas import UserCreate

    user = await user_manager.create(
        UserCreate(
            email=invite.email,
            password=payload.password,
            full_name=invite.full_name,
            is_verified=True,  # invite recipient is verified by possession of token
        )
    )
    # Grant every RBAC role the invite carried.
    for role_code in invite.role_codes:
        await assign_role(session, user_id=user.id, role_code=role_code)

    invite.accepted_at = now
    await record_audit(
        session,
        actor_user_id=user.id,
        entity="invite",
        entity_id=invite.id,
        action="accept",
        diff={
            "email": invite.email,
            "role_codes": invite.role_codes,
            "user_id": user.id,
        },
    )
    await record_audit(
        session,
        actor_user_id=user.id,
        entity="user",
        entity_id=user.id,
        action="create",
        diff={
            "email": user.email,
            "role_codes": invite.role_codes,
            "via": "invite",
        },
    )
    await session.commit()

    log.info("invite.accepted", invite_id=invite.id, user_id=user.id)
    return {"user_id": user.id, "email": user.email}
