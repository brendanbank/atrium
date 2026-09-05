# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Job-runner failure bookkeeping and retry policy (issue #254).

The regression these pin: a handler that dies inside ``flush()`` leaves
the session inactive, so the failure record written afterwards used to
be discarded at commit. The row stayed ``pending, attempts=0``, the
queue re-served it every tick forever, and ``PendingRollbackError``
escaped ``run_one`` and killed the rest of the tick — while the
``job.failed`` log line said everything was handled.

A test that only asserts the *logged* message passes over the bug, so
every case here reads the durable row back from the database.

The flush failure is manufactured with an FK violation (a
``notifications`` row pointing at a user id that does not exist) because
it fails the same way the real-world triggers did — inside the flush,
mid-transaction, with the session left needing a rollback.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.builtin_handlers import register_builtin_handlers
from app.jobs.runner import (
    PermanentJobError,
    clear_handlers,
    register_handler,
    run_one,
)
from app.models.enums import JobState
from app.models.ops import Notification, ScheduledJob

MISSING_USER_ID = 987_654_321


@pytest.fixture(autouse=True)
def _isolated_registry():
    """Fresh handler registry per case, builtins restored afterwards so
    the process-wide dict doesn't leak an empty state into the rest of
    the suite."""
    clear_handlers()
    yield
    clear_handlers()
    register_builtin_handlers()


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _queue(session: AsyncSession, job_type: str) -> int:
    # MySQL DATETIME(0) rounds half-up; nudge into the past so
    # ``run_at <= NOW()`` holds on the next claim (CLAUDE.md gotcha #1).
    job = ScheduledJob(
        job_type=job_type,
        run_at=_utcnow_naive() - timedelta(seconds=1),
        state=JobState.PENDING.value,
        payload={},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return int(job.id)


async def _reread(session: AsyncSession, job_id: int) -> ScheduledJob:
    """Re-read the row from the database, not the identity map.

    ``run_one`` commits with ``expire_on_commit=False``, so an in-memory
    instance would happily report the values the *lost* write set —
    exactly the illusion this module exists to disprove.
    """
    session.expire_all()
    job = (
        await session.execute(select(ScheduledJob).where(ScheduledJob.id == job_id))
    ).scalar_one_or_none()
    assert job is not None
    return job


async def _flush_failing_handler(
    session: AsyncSession, job: ScheduledJob, payload: dict[str, Any]
) -> None:
    """Die the way the reported failures died: inside a flush."""
    session.add(
        Notification(user_id=MISSING_USER_ID, kind="orphan", payload={})
    )
    await session.flush()


async def test_flush_failure_records_its_own_bookkeeping(session: AsyncSession):
    """The core defect: the failure record must survive the failure."""
    register_handler("test.flush_boom", _flush_failing_handler)
    job_id = await _queue(session, "test.flush_boom")

    assert await run_one(session) is True

    job = await _reread(session, job_id)
    assert job.state == JobState.FAILED.value
    assert job.attempts == 1
    assert job.last_error is not None
    assert "IntegrityError" in job.last_error


async def test_flush_failure_does_not_leave_an_immortal_job(session: AsyncSession):
    """Before the fix the row stayed PENDING, so every tick re-served
    the same job and everything behind it starved."""
    register_handler("test.flush_boom", _flush_failing_handler)
    await _queue(session, "test.flush_boom")

    assert await run_one(session) is True
    # Queue is now empty: the poison row is terminal, not re-served.
    assert await run_one(session) is False


async def test_flush_failure_does_not_wedge_the_rest_of_the_tick(
    session: AsyncSession,
):
    """``PendingRollbackError`` used to escape ``run_one``, so ``_tick``
    logged ``worker.tick.unhandled`` and abandoned every job it had not
    reached yet."""
    ran: list[str] = []

    async def ok(_s: AsyncSession, _j: ScheduledJob, _p: dict[str, Any]) -> None:
        ran.append("ok")

    register_handler("test.flush_boom", _flush_failing_handler)
    register_handler("test.ok", ok)

    await _queue(session, "test.flush_boom")
    good_id = await _queue(session, "test.ok")

    assert await run_one(session) is True  # poison row, must not raise
    assert await run_one(session) is True  # the job queued behind it

    assert ran == ["ok"]
    assert (await _reread(session, good_id)).state == JobState.DONE.value


async def test_handler_writes_are_rolled_back_on_failure(session: AsyncSession):
    """A failed job is one transaction: its partial work does not get
    committed alongside the failure marker."""

    async def half_done(
        sess: AsyncSession, job: ScheduledJob, _p: dict[str, Any]
    ) -> None:
        sess.add(
            ScheduledJob(
                job_type="test.side_effect",
                run_at=_utcnow_naive() + timedelta(days=1),
                state=JobState.PENDING.value,
                payload={},
            )
        )
        await sess.flush()
        raise RuntimeError("changed my mind")

    register_handler("test.half_done", half_done)
    job_id = await _queue(session, "test.half_done")

    assert await run_one(session) is True

    assert (await _reread(session, job_id)).state == JobState.FAILED.value
    session.expire_all()
    leftovers = (
        await session.execute(
            select(ScheduledJob).where(ScheduledJob.job_type == "test.side_effect")
        )
    ).scalars().all()
    assert leftovers == []


async def test_success_counts_the_attempt(session: AsyncSession):
    seen: list[int] = []

    async def ok(_s: AsyncSession, job: ScheduledJob, _p: dict[str, Any]) -> None:
        # The handler sees the number of the try it is running.
        seen.append(job.attempts)

    register_handler("test.ok", ok)
    job_id = await _queue(session, "test.ok")

    assert await run_one(session) is True

    job = await _reread(session, job_id)
    assert job.state == JobState.DONE.value
    assert job.attempts == 1
    assert job.last_error is None
    assert seen == [1]


async def test_retry_reschedules_until_the_budget_runs_out(session: AsyncSession):
    """``max_attempts > 1`` keeps the row PENDING and pushes ``run_at``
    out, so a transient failure is not a permanent drop."""
    register_handler(
        "test.flaky",
        _flush_failing_handler,
        max_attempts=3,
        backoff_seconds=(60, 300, 900),
    )
    job_id = await _queue(session, "test.flaky")

    for expected_attempt, expected_delay in ((1, 60), (2, 300)):
        assert await run_one(session) is True
        job = await _reread(session, job_id)
        assert job.state == JobState.PENDING.value
        assert job.attempts == expected_attempt
        assert job.last_error is not None
        # Rescheduled into the future, so the next tick skips it.
        # MySQL DATETIME(0) rounds half-up, hence the +1s slack on top.
        delay = (job.run_at - _utcnow_naive()).total_seconds()
        assert expected_delay - 30 < delay <= expected_delay + 1
        assert await run_one(session) is False

        # Fast-forward instead of sleeping through the backoff.
        job.run_at = _utcnow_naive() - timedelta(seconds=1)
        await session.commit()

    assert await run_one(session) is True
    job = await _reread(session, job_id)
    assert job.state == JobState.FAILED.value
    assert job.attempts == 3


async def test_permanent_job_error_skips_the_retry_budget(session: AsyncSession):
    """Some failures will never succeed on a retry — spending three
    tries and 15 minutes on them just delays the loud failure."""

    async def hopeless(
        _s: AsyncSession, _j: ScheduledJob, _p: dict[str, Any]
    ) -> None:
        raise PermanentJobError("payload will never be valid")

    register_handler("test.hopeless", hopeless, max_attempts=3)
    job_id = await _queue(session, "test.hopeless")

    assert await run_one(session) is True

    job = await _reread(session, job_id)
    assert job.state == JobState.FAILED.value
    assert job.attempts == 1
    assert job.last_error is not None
    assert "PermanentJobError" in job.last_error


def test_register_handler_rejects_a_zero_attempt_budget():
    async def _noop(_s, _j, _p):  # type: ignore[no-untyped-def]
        return None

    with pytest.raises(ValueError):
        register_handler("test.bad", _noop, max_attempts=0)
    with pytest.raises(ValueError):
        register_handler("test.bad", _noop, max_attempts=2, backoff_seconds=())
