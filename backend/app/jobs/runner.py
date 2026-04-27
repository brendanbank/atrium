# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Job runner — claims and dispatches a single ScheduledJob.

Atrium ships no built-in job handlers. Host apps register them via
`register_handler(job_type, handler)` at startup. The runner looks up
the handler by `job.job_type` and invokes it; jobs without a handler
are cancelled with an explanatory `last_error`.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.schedule import next_due_job
from app.logging import log
from app.models.enums import JobState
from app.models.ops import ScheduledJob

JobHandler = Callable[[AsyncSession, ScheduledJob, dict[str, Any]], Awaitable[None]]

_HANDLERS: dict[str, JobHandler] = {}


def register_handler(job_type: str, handler: JobHandler) -> None:
    """Register a handler for `job_type`. Last registration wins."""
    _HANDLERS[job_type] = handler


def clear_handlers() -> None:
    """Test helper — wipes the registry between cases."""
    _HANDLERS.clear()


async def run_one(session: AsyncSession) -> bool:
    """Claim and run a single due job. Returns True if something was
    processed (caller can loop), False if the queue was empty."""
    job = await next_due_job(session)
    if job is None:
        return False

    handler = _HANDLERS.get(job.job_type)
    if handler is None:
        log.warning(
            "job.no_handler",
            job_id=job.id,
            job_type=job.job_type,
        )
        job.state = JobState.CANCELLED.value
        job.last_error = f"no handler registered for job_type={job.job_type!r}"
        await session.commit()
        return True

    job.attempts = (job.attempts or 0) + 1
    try:
        await handler(session, job, job.payload or {})
        job.state = JobState.DONE.value
        job.last_error = None
    except Exception as exc:
        job.state = JobState.FAILED.value
        job.last_error = f"{exc.__class__.__name__}: {exc}"
        log.error(
            "job.failed",
            job_id=job.id,
            job_type=job.job_type,
            error=job.last_error,
        )
    await session.commit()
    return True
