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
import signal
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.db import get_engine, get_session_factory
from app.jobs.runner import run_one
from app.logging import configure_logging, log
from app.models.ops import AppSetting

POLL_INTERVAL_SECONDS = 60
MAX_JOBS_PER_TICK = 50
HEARTBEAT_INTERVAL_SECONDS = 30
HEARTBEAT_KEY = "worker_heartbeat"


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


async def main() -> None:
    configure_logging()
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
    scheduler.start()

    # Kick once immediately so /health doesn't see a "worker: no heartbeat"
    # failure in the first 30 seconds after a cold start, and so a
    # just-created booking's "agent_blocked_dates" fires without waiting a
    # full poll interval after worker start.
    await _heartbeat()
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
