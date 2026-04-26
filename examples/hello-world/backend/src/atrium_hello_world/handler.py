"""Worker handler for ``hello_count`` jobs.

The runner claims a ``scheduled_jobs`` row, looks up the handler by
``job_type``, and invokes it with the session, the job row, and the
JSON payload. We re-check ``enabled`` here so a toggle that lands
between enqueue and drain still skips the increment — useful when the
operator flips off mid-tick.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import log
from app.models.ops import ScheduledJob

from .models import HelloState


async def hello_count_handler(
    session: AsyncSession,
    job: ScheduledJob,
    payload: dict[str, Any],
) -> None:
    del job, payload  # tick-driven, no per-row data
    result = await session.execute(
        update(HelloState)
        .where(HelloState.id == 1, HelloState.enabled.is_(True))
        .values(counter=HelloState.counter + 1)
    )
    if result.rowcount:
        log.info("hello_world.counter_incremented", rowcount=result.rowcount)
