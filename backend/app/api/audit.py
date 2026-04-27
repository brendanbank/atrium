# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Owner-only audit log view."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import require_perm
from app.db import get_session
from app.models.auth import User
from app.models.ops import AuditLog
from app.schemas.audit import AuditEntry, AuditPage

router = APIRouter(prefix="/admin/audit", tags=["admin"])


@router.get("", response_model=AuditPage)
async def list_audit(
    _actor: User = Depends(require_perm("audit.read")),
    session: AsyncSession = Depends(get_session),
    entity: str | None = Query(default=None),
    actor_user_id: int | None = Query(default=None),
    since: date | None = Query(default=None, description="Inclusive start date"),
    until: date | None = Query(default=None, description="Exclusive end date"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AuditPage:
    stmt = (
        select(AuditLog, User.email)
        .join(User, User.id == AuditLog.actor_user_id, isouter=True)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    )
    count_stmt = select(func.count(AuditLog.id))

    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
        count_stmt = count_stmt.where(AuditLog.entity == entity)
    if actor_user_id is not None:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
        count_stmt = count_stmt.where(AuditLog.actor_user_id == actor_user_id)
    if since is not None:
        stmt = stmt.where(AuditLog.created_at >= since)
        count_stmt = count_stmt.where(AuditLog.created_at >= since)
    if until is not None:
        stmt = stmt.where(AuditLog.created_at < until)
        count_stmt = count_stmt.where(AuditLog.created_at < until)

    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(stmt.limit(limit).offset(offset))).all()

    items = [
        AuditEntry(
            id=a.id,
            actor_user_id=a.actor_user_id,
            actor_email=email,
            entity=a.entity,
            entity_id=a.entity_id,
            action=a.action,
            diff=a.diff,
            created_at=a.created_at,
        )
        for a, email in rows
    ]
    return AuditPage(items=items, total=int(total or 0))
