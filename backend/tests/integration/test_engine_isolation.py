# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Engine-level isolation guard.

Atrium pins ``isolation_level="READ COMMITTED"`` on the async engine so
the worker's ``SELECT ... FOR UPDATE SKIP LOCKED`` claim on
``scheduled_jobs`` only takes a record lock on the chosen row. Under
the MySQL default (REPEATABLE READ), InnoDB also takes next-key /
supremum gap locks on the surrounding index — and those gap locks live
for the entire transaction (i.e. the full duration of the job
handler), which deadlocks against any API endpoint that touches
``scheduled_jobs`` while holding other locks (issue #152).

This test runs a real connection through ``app.db.get_engine()`` and
asserts MySQL reports the session-level isolation as READ-COMMITTED.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

import app.db as db_module
from app.settings import get_settings


@pytest.mark.asyncio
async def test_engine_session_runs_at_read_committed(mysql_url: str) -> None:
    settings = get_settings()
    original_url = settings.database_url
    settings.database_url = mysql_url

    # ``get_engine`` is a module-level cache. Reset it so the test sees
    # an engine built against ``mysql_url`` with the production kwargs,
    # then restore the cache so subsequent tests in the session keep
    # working against whatever they already had.
    saved_engine = db_module._engine
    saved_factory = db_module._session_factory
    db_module._engine = None
    db_module._session_factory = None

    try:
        engine = db_module.get_engine()
        async with engine.connect() as conn:
            level = (
                await conn.execute(text("SELECT @@session.transaction_isolation"))
            ).scalar_one()
        # MySQL spells it ``READ-COMMITTED`` with a hyphen at the
        # session variable level; SQLAlchemy passes ``READ COMMITTED``
        # with a space. Both are the same isolation.
        assert level == "READ-COMMITTED", (
            f"engine should run at READ COMMITTED to avoid the issue #152 "
            f"deadlock pattern; MySQL reports session isolation = {level!r}"
        )
        await engine.dispose()
    finally:
        settings.database_url = original_url
        db_module._engine = saved_engine
        db_module._session_factory = saved_factory
