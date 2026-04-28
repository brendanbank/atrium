# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""APScheduler worker.

One process, one container. Every ``POLL_INTERVAL_SECONDS`` it drains
due rows out of ``scheduled_jobs`` and dispatches them. We don't use
APScheduler's own job store — the scheduled_jobs table is our source
of truth so the UI can see/cancel pending work.

Running a single worker keeps things simple; multiple workers would
also be safe because ``next_due_job`` uses SELECT ... FOR UPDATE SKIP
LOCKED to claim exactly one row at a time.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import signal
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import and_, exists, select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.db import get_engine, get_session_factory
from app.host_sdk.worker import HostWorkerCtx
from app.jobs.builtin_handlers import register_builtin_handlers
from app.jobs.runner import run_one
from app.logging import configure_logging, log
from app.models.email_outbox import EmailOutbox
from app.models.enums import JobState
from app.models.ops import AppSetting, ScheduledJob

POLL_INTERVAL_SECONDS = 60
MAX_JOBS_PER_TICK = 50
HEARTBEAT_INTERVAL_SECONDS = 30
HEARTBEAT_KEY = "worker_heartbeat"
AUDIT_PRUNE_INTERVAL_SECONDS = 24 * 60 * 60
ACCOUNT_HARD_DELETE_INTERVAL_SECONDS = 24 * 60 * 60
OUTBOX_DRAIN_INTERVAL_SECONDS = 60
MAX_OUTBOX_PER_TICK = 50


async def _tick() -> None:
    """Drain up to ``MAX_JOBS_PER_TICK`` jobs. Each job runs in its own
    session/transaction so a failure doesn't poison the next one."""
    factory = get_session_factory()
    for _ in range(MAX_JOBS_PER_TICK):
        async with factory() as session:
            try:
                did_work = await run_one(session)
            except Exception as exc:
                log.error("worker.tick.unhandled", error=str(exc))
                await session.rollback()
                return
        if not did_work:
            return


async def _drain_outbox() -> None:
    """Convert due ``email_outbox`` rows into ``scheduled_jobs`` rows.

    The outbox is the durable side of the email queue; the scheduled
    jobs table is what the runner actually drains. Bridging the two on
    a 60s tick lets ``enqueue_and_log`` callers stay simple (just
    insert a pending row) and keeps the runner's contract narrow (one
    job, one handler invocation).

    The exists()-guard keeps rapid ticks from piling up duplicate
    scheduled_jobs for the same outbox row when a previous tick's job
    hasn't been claimed yet.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            stmt = (
                select(EmailOutbox.id)
                .where(
                    EmailOutbox.status == "pending",
                    EmailOutbox.next_attempt_at
                    <= datetime.now(UTC).replace(tzinfo=None),
                    ~exists().where(
                        and_(
                            ScheduledJob.job_type == "email_send",
                            ScheduledJob.state == JobState.PENDING.value,
                            ScheduledJob.payload["outbox_id"] == EmailOutbox.id,
                        )
                    ),
                )
                .order_by(EmailOutbox.next_attempt_at.asc(), EmailOutbox.id.asc())
                .limit(MAX_OUTBOX_PER_TICK)
            )
            outbox_ids = (await session.execute(stmt)).scalars().all()
            if not outbox_ids:
                return

            run_at = datetime.now(UTC).replace(tzinfo=None)
            for outbox_id in outbox_ids:
                session.add(
                    ScheduledJob(
                        job_type="email_send",
                        run_at=run_at,
                        state=JobState.PENDING.value,
                        payload={"outbox_id": int(outbox_id)},
                    )
                )
            await session.commit()
            log.info("worker.outbox_drain", enqueued=len(outbox_ids))
        except Exception as exc:
            log.error("worker.outbox_drain.failed", error=str(exc))
            await session.rollback()


async def _heartbeat() -> None:
    """Upsert ``app_settings[worker_heartbeat]`` so /health can detect a
    dead worker. MySQL's ON DUPLICATE KEY UPDATE is atomic and doesn't
    need a pre-read — matches the tone of a fire-and-forget beacon."""
    now_iso = datetime.now(UTC).isoformat()
    factory = get_session_factory()
    async with factory() as session:
        try:
            stmt = mysql_insert(AppSetting).values(
                key=HEARTBEAT_KEY, value={"ts": now_iso}
            )
            stmt = stmt.on_duplicate_key_update(value=stmt.inserted.value)
            await session.execute(stmt)
            await session.commit()
        except Exception as exc:
            log.error("worker.heartbeat.failed", error=str(exc))
            await session.rollback()


async def _enqueue_audit_prune() -> None:
    """Insert a ``scheduled_jobs`` row so the runner picks the prune up
    on its next tick. Mirrors ``_heartbeat`` for transaction handling
    so a failure here doesn't tear the worker down."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            session.add(
                ScheduledJob(
                    job_type="audit_prune",
                    # MySQL DATETIME(0) rounds half-up; nudge into the
                    # past so ``run_at <= NOW()`` is true on the next
                    # runner tick (see CLAUDE.md gotcha #1).
                    run_at=datetime.now(UTC).replace(tzinfo=None),
                    state=JobState.PENDING.value,
                    payload={},
                )
            )
            await session.commit()
        except Exception as exc:
            log.error("worker.audit_prune.enqueue_failed", error=str(exc))
            await session.rollback()


async def _enqueue_account_hard_delete() -> None:
    factory = get_session_factory()
    async with factory() as session:
        try:
            session.add(
                ScheduledJob(
                    job_type="account_hard_delete",
                    run_at=datetime.now(UTC).replace(tzinfo=None),
                    state=JobState.PENDING.value,
                    payload={},
                )
            )
            await session.commit()
        except Exception as exc:
            log.error(
                "worker.account_hard_delete.enqueue_failed", error=str(exc)
            )
            await session.rollback()


async def main() -> None:
    configure_logging()
    register_builtin_handlers()
    log.info("worker.startup", poll_interval=POLL_INTERVAL_SECONDS)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _tick,
        trigger=IntervalTrigger(seconds=POLL_INTERVAL_SECONDS),
        id="scheduled-jobs-tick",
        # Letting the trigger set next_run_time is important: explicitly
        # passing next_run_time=None means "pause this job", which silently
        # stops the worker from polling at all.
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        _heartbeat,
        trigger=IntervalTrigger(seconds=HEARTBEAT_INTERVAL_SECONDS),
        id="worker-heartbeat",
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        _enqueue_audit_prune,
        trigger=IntervalTrigger(seconds=AUDIT_PRUNE_INTERVAL_SECONDS),
        id="audit-prune-enqueue",
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        _enqueue_account_hard_delete,
        trigger=IntervalTrigger(seconds=ACCOUNT_HARD_DELETE_INTERVAL_SECONDS),
        id="account-hard-delete-enqueue",
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        _drain_outbox,
        trigger=IntervalTrigger(seconds=OUTBOX_DRAIN_INTERVAL_SECONDS),
        id="email-outbox-drain",
        coalesce=True,
        max_instances=1,
    )

    host_module = os.environ.get("ATRIUM_HOST_MODULE")
    if host_module:
        mod = importlib.import_module(host_module)
        init = getattr(mod, "init_worker", None)
        if callable(init):
            init(HostWorkerCtx(scheduler=scheduler))
        else:
            log.info("host.init_worker.absent", module=host_module)

    scheduler.start()

    # Kick once immediately so /health doesn't see a "worker: no heartbeat"
    # failure in the first 30 seconds after a cold start, and so a
    # just-created booking's "agent_blocked_dates" fires without waiting a
    # full poll interval after worker start.
    await _heartbeat()
    await _drain_outbox()
    await _tick()

    stop = asyncio.Event()

    def _shutdown(*_: object) -> None:
        log.info("worker.shutdown_requested")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)

    try:
        await stop.wait()
    finally:
        scheduler.shutdown(wait=False)
        await get_engine().dispose()
        log.info("worker.stopped")


if __name__ == "__main__":
    asyncio.run(main())
