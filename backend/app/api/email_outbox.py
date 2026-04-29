# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Admin API for the ``email_outbox`` queue.

Two endpoints, both gated on the ``email_outbox.manage`` permission
(seeded by migration 0006):

* ``GET /admin/email-outbox`` — paginated list of outbox rows. Filter by
  status (``pending`` / ``sending`` / ``sent`` / ``dead``) so the
  default view focuses on what the operator actually came to look at:
  rows that haven't gone out yet.
* ``POST /admin/email-outbox/{id}/drain`` — synchronously run a single
  row through the same code path the cron worker uses (see
  :func:`app.jobs.builtin_handlers.drain_outbox_row`). Returns the
  row's post-attempt status so the UI can show ``sent`` / ``pending``
  (retry queued) / ``dead`` inline. Refuses anything but ``pending``
  with a 409 — re-sending an already-delivered row would create a
  duplicate ``email_log`` entry, and the cron tick is the right path
  for ``sending`` rows still being worked.

Audit rows are written for the manual drain so a "who pressed Send
now?" question has an answer.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import require_perm
from app.db import get_session
from app.jobs.builtin_handlers import drain_outbox_row
from app.models.auth import User
from app.models.email_outbox import EmailOutbox
from app.schemas.email_outbox import (
    DrainResult,
    EmailOutboxPage,
    EmailOutboxRow,
)
from app.services.audit import record as record_audit

router = APIRouter(prefix="/admin/email-outbox", tags=["admin"])

# The four terminal-or-transitional statuses an operator might filter
# on. ``sending`` shouldn't normally be visible for long (the worker
# only holds it across a single send attempt) but is included so a
# stuck row from a crashed worker is filterable.
_VALID_STATUSES = {"pending", "sending", "sent", "dead"}


@router.get("", response_model=EmailOutboxPage)
async def list_outbox(
    _actor: User = Depends(require_perm("email_outbox.manage")),
    session: AsyncSession = Depends(get_session),
    status_: str | None = Query(
        default=None,
        alias="status",
        description=(
            "Filter to a single status. Omit for every row. Valid: "
            "pending, sending, sent, dead."
        ),
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> EmailOutboxPage:
    if status_ is not None and status_ not in _VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown status {status_!r}; valid: {sorted(_VALID_STATUSES)}",
        )

    # Pending first (oldest at top so a stuck queue is obvious), then
    # by created_at desc within the bucket. Total count uses the same
    # filter so pagination is correct.
    stmt = select(EmailOutbox).order_by(
        EmailOutbox.next_attempt_at.asc(), EmailOutbox.id.asc()
    )
    count_stmt = select(func.count(EmailOutbox.id))

    if status_ is not None:
        stmt = stmt.where(EmailOutbox.status == status_)
        count_stmt = count_stmt.where(EmailOutbox.status == status_)

    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        await session.execute(stmt.limit(limit).offset(offset))
    ).scalars().all()

    return EmailOutboxPage(
        items=[EmailOutboxRow.model_validate(row) for row in rows],
        total=int(total or 0),
    )


@router.post(
    "/{outbox_id}/drain",
    response_model=DrainResult,
)
async def drain_one(
    outbox_id: int,
    actor: User = Depends(require_perm("email_outbox.manage")),
    session: AsyncSession = Depends(get_session),
) -> DrainResult:
    # Pre-check status before locking so we can refuse 409 early. The
    # drain helper itself is idempotent on already-finalised rows but
    # would silently no-op; the operator pressed a button and deserves
    # a clearer response.
    pre = await session.get(EmailOutbox, outbox_id)
    if pre is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if pre.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"row is {pre.status!r}; only pending rows can be drained "
                "manually"
            ),
        )

    row = await drain_outbox_row(session, outbox_id)
    if row is None:
        # Race: someone deleted the row between the pre-check and the
        # locking SELECT. Surface the 404 the operator would have seen
        # if they'd hit refresh first.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    await record_audit(
        session,
        actor_user_id=actor.id,
        entity="email_outbox",
        entity_id=row.id,
        action="drain",
        diff={
            "template": row.template,
            "to_addr": row.to_addr,
            "result_status": row.status,
            "attempts": row.attempts,
        },
    )
    await session.commit()
    await session.refresh(row)
    return DrainResult(
        id=row.id,
        status=row.status,
        attempts=row.attempts,
        last_error=row.last_error,
        next_attempt_at=row.next_attempt_at,
    )
