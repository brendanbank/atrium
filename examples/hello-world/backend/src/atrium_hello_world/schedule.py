"""APScheduler tick that enqueues a ``hello_count`` job when the demo
is enabled.

The intermediate ``scheduled_jobs`` row (rather than incrementing
inline) is the whole point of the demo — it shows the full atrium
job pipeline: APScheduler interval → row insert → worker drain →
registered handler. Production hosts can pick the simpler "do work
inline in the APScheduler callback" pattern when durability and the
admin job log don't matter.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.db import get_session_factory
from app.logging import log
from app.models.enums import JobState
from app.models.ops import ScheduledJob

from .models import HelloState


async def enqueue_hello_count() -> None:
    factory = get_session_factory()
    async with factory() as session:
        try:
            enabled = (
                await session.execute(
                    select(HelloState.enabled).where(HelloState.id == 1)
                )
            ).scalar_one_or_none()
            if not enabled:
                return
            session.add(
                ScheduledJob(
                    job_type="hello_count",
                    # MySQL DATETIME(0) rounds half-up; a tiny push into
                    # the past makes the next runner tick pick this up
                    # immediately. (CLAUDE.md gotcha #1.)
                    run_at=datetime.now(UTC).replace(tzinfo=None),
                    state=JobState.PENDING.value,
                    payload={},
                )
            )
            await session.commit()
        except Exception as exc:
            log.error("hello_world.enqueue_failed", error=str(exc))
            await session.rollback()
