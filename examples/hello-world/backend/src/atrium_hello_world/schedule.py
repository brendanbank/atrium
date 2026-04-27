# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""APScheduler tick that increments the counter when the demo is
enabled.

Atomic UPDATE WHERE enabled=TRUE so a toggle that lands between two
ticks immediately stops the counter — no need for a separate
"in-flight job" check.

Why inline (instead of inserting a ``scheduled_jobs`` row and letting
the worker's queue-drain run the handler)? Atrium's queue tick is
60 s, which made every counter increment feel like a minute of dead
air. Inline keeps the demo crisp at the configured interval (default
3 s, smoke tests use 2 s). The ``scheduled_jobs`` queue is the right
tool for jobs that need durability across worker restarts or atomic
ordering — it's documented in the README's "when to use the queue"
section, and ``app.jobs.runner.register_handler`` is still part of
atrium's surface even though the example no longer exercises it.
"""
from __future__ import annotations

from sqlalchemy import update

from app.db import get_session_factory
from app.logging import log

from .models import HelloState


async def tick_hello_count() -> None:
    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                update(HelloState)
                .where(HelloState.id == 1, HelloState.enabled.is_(True))
                .values(counter=HelloState.counter + 1)
            )
            await session.commit()
            if result.rowcount:
                log.info("hello_world.counter_incremented")
        except Exception as exc:
            log.error("hello_world.tick_failed", error=str(exc))
            await session.rollback()
