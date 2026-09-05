# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Job runner — claims and dispatches a single ScheduledJob.

Atrium ships three platform-owned handlers (``app.jobs.builtin_handlers``);
everything domain-specific belongs in host apps, which register handlers
via `register_handler(job_type, handler)` at startup. The runner looks up
the handler by `job.job_type` and invokes it; jobs without a handler are
cancelled with an explanatory `last_error`.

Two rules govern the failure path — both learned the hard way (issue
#254), both easy to undo by accident:

* **Roll back before recording.** A handler that dies inside ``flush()``
  leaves the session inactive. Writing the failure bookkeeping onto that
  session raises ``PendingRollbackError`` at commit, so the state, the
  error message and the attempts increment are all discarded together.
  The row stays ``pending, attempts=0``, the queue re-serves it every
  tick forever, and the ``job.failed`` log line makes it look handled.
* **Never read the stale ORM instance afterwards.** A lazy load on an
  inactive session re-raises rather than returning a value, which
  re-creates the same wedge one frame further along. Everything the
  failure path needs (id, job_type, payload) is copied into locals
  before the handler runs.

Retries are opt-in per handler: ``register_handler(..., max_attempts=3)``
pushes ``run_at`` into the future and leaves the row PENDING instead of
failing it on the first throw. The default of 1 keeps the historical
one-shot behaviour, so registering a handler the old way changes
nothing.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.schedule import next_due_job
from app.logging import log
from app.models.enums import JobState
from app.models.ops import ScheduledJob

JobHandler = Callable[[AsyncSession, ScheduledJob, dict[str, Any]], Awaitable[None]]

# Retry delays indexed by the number of tries already taken. Same shape
# as the email outbox's private schedule (builtin_handlers), shortened
# for generic work: a minute, five, fifteen.
DEFAULT_BACKOFF_SECONDS: tuple[int, ...] = (60, 300, 900)


class PermanentJobError(Exception):
    """Raise from a handler to burn the remaining retry budget.

    A handler registered with ``max_attempts > 1`` has every exception
    rescheduled by default, which is right for a provider 429/529 or a
    dropped connection and wrong for a malformed payload or a value that
    will never fit its column. Raising (or re-raising ``from``) this
    marks the job FAILED immediately rather than spending the budget on
    a certain failure.
    """


def _utcnow_naive() -> datetime:
    """MySQL DATETIME columns here are naive — strip tz for comparisons."""
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class _HandlerPolicy:
    """A registered handler plus how many tries its jobs get."""

    handler: JobHandler
    max_attempts: int
    backoff_seconds: tuple[int, ...]

    def retry_delay(self, attempts: int) -> timedelta | None:
        """How long to wait before try ``attempts + 1``, or None when the
        budget is spent. ``attempts`` counts tries already taken."""
        if attempts >= self.max_attempts:
            return None
        idx = min(max(attempts - 1, 0), len(self.backoff_seconds) - 1)
        return timedelta(seconds=self.backoff_seconds[idx])


_HANDLERS: dict[str, _HandlerPolicy] = {}


def register_handler(
    job_type: str,
    handler: JobHandler,
    *,
    max_attempts: int = 1,
    backoff_seconds: Sequence[int] | None = None,
) -> None:
    """Register a handler for `job_type`. Last registration wins.

    ``max_attempts`` is the total number of tries a job of this type
    gets, retries included. The default of 1 is the historical
    behaviour: one throw and the row is FAILED. Anything higher leaves
    the row PENDING with ``run_at`` pushed out by ``backoff_seconds``
    (defaulting to :data:`DEFAULT_BACKOFF_SECONDS`) until the budget
    runs out; the last delay repeats if the schedule is shorter than
    the budget.
    """
    if max_attempts < 1:
        raise ValueError("register_handler: 'max_attempts' must be >= 1")
    delays = tuple(backoff_seconds) if backoff_seconds is not None else DEFAULT_BACKOFF_SECONDS
    if not delays:
        raise ValueError("register_handler: 'backoff_seconds' must be non-empty")
    _HANDLERS[job_type] = _HandlerPolicy(
        handler=handler,
        max_attempts=max_attempts,
        backoff_seconds=delays,
    )


def clear_handlers() -> None:
    """Test helper — wipes the registry between cases."""
    _HANDLERS.clear()


async def run_one(session: AsyncSession) -> bool:
    """Claim and run a single due job. Returns True if something was
    processed (caller can loop), False if the queue was empty."""
    job = await next_due_job(session)
    if job is None:
        return False

    # Copy what the failure path needs while the session is still known
    # good — see the module docstring's second rule.
    job_id = int(job.id)
    job_type = job.job_type
    payload = job.payload or {}

    policy = _HANDLERS.get(job_type)
    if policy is None:
        log.warning(
            "job.no_handler",
            job_id=job_id,
            job_type=job_type,
        )
        job.state = JobState.CANCELLED.value
        job.last_error = f"no handler registered for job_type={job_type!r}"
        await session.commit()
        return True

    # Set before the try so the handler can read ``job.attempts`` as
    # "which try is this". The failure path re-applies ``attempt``
    # rather than incrementing again, so the counter lands exactly once
    # whether or not the rollback discarded this write.
    attempt = (job.attempts or 0) + 1
    job.attempts = attempt
    try:
        await policy.handler(session, job, payload)
    except Exception as exc:
        await _record_failure(session, job_id, job_type, attempt, policy, exc)
        return True

    job.state = JobState.DONE.value
    job.last_error = None
    await session.commit()
    return True


async def _record_failure(
    session: AsyncSession,
    job_id: int,
    job_type: str,
    attempt: int,
    policy: _HandlerPolicy,
    exc: BaseException,
) -> None:
    """Persist the outcome of a failed handler run, then decide whether
    the job gets another try.

    The rollback comes first and nothing may be written before it: a
    handler that failed at flush leaves the session inactive, and every
    pending change — including ``run_one``'s attempts increment — dies
    with the rollback. See the module docstring.
    """
    error = f"{exc.__class__.__name__}: {exc}"
    await session.rollback()

    # The rollback also dropped the FOR UPDATE claim ``next_due_job``
    # took, so re-take it before writing. Atrium ships one worker, but
    # the claim is written to be safe with several: re-locking plus the
    # state check below stop us from stomping a peer that grabbed the
    # row in the gap and finished it.
    job = (
        await session.execute(
            select(ScheduledJob).where(ScheduledJob.id == job_id).with_for_update()
        )
    ).scalar_one_or_none()
    if job is None or job.state != JobState.PENDING.value:
        log.error(
            "job.failed.not_recorded",
            job_id=job_id,
            job_type=job_type,
            reason="row missing" if job is None else f"state={job.state}",
            error=error,
        )
        await session.rollback()
        return

    job.attempts = attempt
    job.last_error = error

    delay = (
        None
        if isinstance(exc, PermanentJobError)
        else policy.retry_delay(attempt)
    )
    if delay is None:
        job.state = JobState.FAILED.value
        log.error(
            "job.failed",
            job_id=job_id,
            job_type=job_type,
            attempts=attempt,
            error=error,
        )
    else:
        # Stays PENDING; only the due time moves.
        job.run_at = _utcnow_naive() + delay
        log.warning(
            "job.retry_scheduled",
            job_id=job_id,
            job_type=job_type,
            attempts=attempt,
            retry_in_seconds=int(delay.total_seconds()),
            error=error,
        )
    await session.commit()
