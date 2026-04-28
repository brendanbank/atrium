# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""``HostWorkerCtx`` + the typed ``register_job_handler`` host hook.

Hosts call ``host.register_job_handler(kind=..., handler=...)`` from
``init_worker(host)``; the runner's existing dispatch (``run_one``)
picks up the handler against the same ``_HANDLERS`` dict that internal
``register_handler`` writes to.

The contract:

1. A registered handler runs when a matching ``ScheduledJob`` row is
   drained.
2. A handler that throws is contained — the runner marks the job
   FAILED with ``last_error``, logs ``job.failed``, and the worker
   keeps polling. (This is already in ``run_one``; the test here
   pins the behaviour against the host-facing path so the contract
   referenced in ``HostWorkerCtx.register_job_handler`` doesn't
   regress.)
3. An unknown ``job_type`` is rejected loudly — the row is moved to
   CANCELLED with an explanatory ``last_error``.
4. Calling ``register_job_handler`` with an empty ``kind`` raises
   immediately (cheap fail-fast at startup).
5. Re-registering the same ``kind`` is allowed but emits a
   ``host.job_handler.duplicate`` warning so collisions are visible.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.host_sdk.worker import HostWorkerCtx
from app.jobs.runner import clear_handlers, run_one
from app.models.enums import JobState
from app.models.ops import ScheduledJob


@pytest.fixture
def host_ctx() -> HostWorkerCtx:
    """Fresh registry per test — clears the runner's process-wide
    ``_HANDLERS`` dict so each case starts from a known state."""
    clear_handlers()
    # ``scheduler`` is unused by the registry tests; pass a sentinel so
    # the dataclass is fully constructed without spinning up
    # APScheduler. The contract only constrains how
    # ``register_job_handler`` interacts with the runner.
    return HostWorkerCtx(scheduler=object())  # type: ignore[arg-type]


@pytest_asyncio.fixture
async def queued_job(session: AsyncSession):
    """Yield a callable that queues a ``ScheduledJob`` row of the
    requested ``job_type`` for the runner to drain."""

    async def _queue(job_type: str, payload: dict[str, Any] | None = None) -> int:
        # MySQL DATETIME(0) rounds half-up; subtract a second so
        # ``run_at <= NOW()`` is true on the next ``next_due_job``
        # query (CLAUDE.md gotcha #1).
        run_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        job = ScheduledJob(
            job_type=job_type,
            run_at=run_at,
            state=JobState.PENDING.value,
            payload=payload or {},
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return int(job.id)

    return _queue


@pytest.mark.asyncio
async def test_registered_handler_runs(
    session: AsyncSession, host_ctx: HostWorkerCtx, queued_job
) -> None:
    """The runner finds the host-registered handler and invokes it."""
    seen: list[dict[str, Any]] = []

    async def handler(sess: AsyncSession, job: ScheduledJob, payload: dict[str, Any]) -> None:
        seen.append(payload)

    host_ctx.register_job_handler(
        kind="test.host_runs",
        handler=handler,
        description="unit test",
    )

    job_id = await queued_job("test.host_runs", {"hello": "world"})
    did_work = await run_one(session)

    assert did_work is True
    assert seen == [{"hello": "world"}]

    await session.commit()
    refreshed = await session.get(ScheduledJob, job_id)
    assert refreshed is not None
    assert refreshed.state == JobState.DONE.value
    assert refreshed.last_error is None


@pytest.mark.asyncio
async def test_handler_exception_is_contained(
    session: AsyncSession, host_ctx: HostWorkerCtx, queued_job
) -> None:
    """A throwing handler marks the row FAILED and the runner returns
    True so the worker keeps draining the next row instead of dying."""

    async def boom(sess: AsyncSession, job: ScheduledJob, payload: dict[str, Any]) -> None:
        raise RuntimeError("kaboom")

    host_ctx.register_job_handler(kind="test.host_throws", handler=boom)

    job_id = await queued_job("test.host_throws")
    did_work = await run_one(session)

    assert did_work is True

    await session.commit()
    refreshed = await session.get(ScheduledJob, job_id)
    assert refreshed is not None
    assert refreshed.state == JobState.FAILED.value
    assert refreshed.last_error is not None
    assert "kaboom" in refreshed.last_error


@pytest.mark.asyncio
async def test_unknown_kind_is_rejected_loudly(
    session: AsyncSession, host_ctx: HostWorkerCtx, queued_job
) -> None:
    """Jobs without a registered handler are CANCELLED with a clear
    ``last_error`` rather than silently retried forever."""
    job_id = await queued_job("test.host_unknown")
    did_work = await run_one(session)

    assert did_work is True

    await session.commit()
    refreshed = await session.get(ScheduledJob, job_id)
    assert refreshed is not None
    assert refreshed.state == JobState.CANCELLED.value
    assert refreshed.last_error is not None
    assert "test.host_unknown" in refreshed.last_error


def test_empty_kind_raises(host_ctx: HostWorkerCtx) -> None:
    """A misconfigured registration (typo, missing constant) fails
    fast at startup instead of silently shadowing a real kind."""

    async def _noop(_s: AsyncSession, _j: ScheduledJob, _p: dict[str, Any]) -> None:
        return None

    with pytest.raises(ValueError):
        host_ctx.register_job_handler(kind="", handler=_noop)


def test_duplicate_registration_warns(
    host_ctx: HostWorkerCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Last-write-wins, but the collision is observable in logs.

    Spy on ``log.warning`` directly — structlog's default logger
    factory in the unconfigured (test) environment writes to stdout,
    not stdlib logging, so ``caplog`` doesn't see the event.
    """
    captured: list[tuple[str, dict[str, object]]] = []

    def _spy(event: str, **kwargs: object) -> None:
        captured.append((event, kwargs))

    from app.host_sdk import worker as host_worker

    monkeypatch.setattr(host_worker.log, "warning", _spy)

    async def first(_s, _j, _p):  # type: ignore[no-untyped-def]
        return None

    async def second(_s, _j, _p):  # type: ignore[no-untyped-def]
        return None

    host_ctx.register_job_handler(kind="test.host_dup", handler=first)
    host_ctx.register_job_handler(kind="test.host_dup", handler=second)

    duplicate_events = [
        kwargs for event, kwargs in captured if event == "host.job_handler.duplicate"
    ]
    assert len(duplicate_events) == 1
    assert duplicate_events[0]["kind"] == "test.host_dup"
