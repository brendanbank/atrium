# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Admin CRUD for reminder rules. Owner-only."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import require_perm
from app.db import get_session
from app.models.auth import User
from app.models.email_template import EmailTemplate
from app.models.reminder_rule import ReminderRule
from app.schemas.reminder_rule import (
    ReminderRuleCreate,
    ReminderRuleRead,
    ReminderRuleUpdate,
)
from app.services.audit import record as record_audit

router = APIRouter(prefix="/admin/reminder-rules", tags=["admin"])


@router.get("", response_model=list[ReminderRuleRead])
async def list_rules(
    _actor: User = Depends(require_perm("reminder_rule.manage")),
    session: AsyncSession = Depends(get_session),
) -> list[ReminderRule]:
    rows = await session.execute(
        select(ReminderRule).order_by(ReminderRule.id)
    )
    return list(rows.scalars().all())


async def _check_template_exists(session: AsyncSession, key: str) -> None:
    if (await session.get(EmailTemplate, key)) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"email template '{key}' does not exist",
        )


@router.post("", response_model=ReminderRuleRead, status_code=status.HTTP_201_CREATED)
async def create_rule(
    payload: ReminderRuleCreate,
    owner: User = Depends(require_perm("reminder_rule.manage")),
    session: AsyncSession = Depends(get_session),
) -> ReminderRule:
    await _check_template_exists(session, payload.template_key)
    rule = ReminderRule(**payload.model_dump())
    session.add(rule)
    await session.flush()
    await record_audit(
        session,
        actor_user_id=owner.id,
        entity="reminder_rule",
        entity_id=rule.id,
        action="create",
        diff=payload.model_dump(),
    )
    await session.commit()
    await session.refresh(rule)
    return rule


@router.patch("/{rule_id}", response_model=ReminderRuleRead)
async def update_rule(
    rule_id: int,
    payload: ReminderRuleUpdate,
    owner: User = Depends(require_perm("reminder_rule.manage")),
    session: AsyncSession = Depends(get_session),
) -> ReminderRule:
    rule = await session.get(ReminderRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    updates = payload.model_dump(exclude_unset=True)
    if "template_key" in updates:
        await _check_template_exists(session, updates["template_key"])
    for k, v in updates.items():
        setattr(rule, k, v)
    await record_audit(
        session,
        actor_user_id=owner.id,
        entity="reminder_rule",
        entity_id=rule.id,
        action="update",
        diff=updates,
    )
    await session.commit()
    await session.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: int,
    owner: User = Depends(require_perm("reminder_rule.manage")),
    session: AsyncSession = Depends(get_session),
) -> None:
    rule = await session.get(ReminderRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await record_audit(
        session,
        actor_user_id=owner.id,
        entity="reminder_rule",
        entity_id=rule.id,
        action="delete",
        diff={"name": rule.name, "kind": rule.kind},
    )
    await session.delete(rule)
    await session.commit()
