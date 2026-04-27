# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Queue helpers for the scheduled_jobs table.

Atrium ships only the claim primitive (`next_due_job`). Host apps
define their own scheduling helpers (e.g. "schedule a reminder N days
before X happens") on top.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import JobState
from app.models.ops import ScheduledJob


def _utcnow_naive() -> datetime:
    """MySQL DATETIME columns here are naive — strip tz for comparisons."""
    return datetime.now(UTC).replace(tzinfo=None)


async def next_due_job(session: AsyncSession) -> ScheduledJob | None:
    """Claim the oldest pending job whose run_at has elapsed.

    Uses SELECT ... FOR UPDATE SKIP LOCKED so multiple workers can run
    safely.
    """
    stmt = (
        select(ScheduledJob)
        .where(
            ScheduledJob.state == JobState.PENDING.value,
            ScheduledJob.run_at <= _utcnow_naive(),
        )
        .order_by(ScheduledJob.run_at.asc(), ScheduledJob.id.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()
