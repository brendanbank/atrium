# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Atrium host bootstrap entry points.

The atrium image imports this module on startup when the operator sets
``ATRIUM_HOST_MODULE=atrium_hello_world.bootstrap``:

- ``init_app(app)`` runs once during ``create_app()`` — after every
  atrium router is included and before the ASGI app starts serving.
  We use it to mount our router; permissions are seeded by the alembic
  migration (``alembic/versions/0001_hello_state.py``) using the sync
  form of ``app.auth.rbac_seed.seed_permissions_sync``. Migration-time
  seeding sidesteps the lifespan-vs-add_event_handler conflict in
  modern FastAPI and matches the schema-shaped nature of permissions.
- ``init_worker(scheduler)`` runs on worker startup, after atrium's
  built-in handlers register and before APScheduler starts. We add
  the recurring counter-increment tick.
"""
from __future__ import annotations

import os

from fastapi import FastAPI

# Default tick interval. Smoke tests and the dev compose overlay set
# HELLO_TICK_SECONDS=2 so the spec lands in seconds; the standalone
# demo defaults to 3 s for visible feedback without spamming the log.
DEFAULT_TICK_SECONDS = 3


def init_app(app: FastAPI) -> None:
    from .router import router

    app.include_router(router)


def init_worker(scheduler) -> None:  # noqa: ANN001 — APScheduler types are loose
    from .schedule import tick_hello_count

    seconds = int(os.environ.get("HELLO_TICK_SECONDS", str(DEFAULT_TICK_SECONDS)))
    scheduler.add_job(
        tick_hello_count,
        "interval",
        seconds=seconds,
        id="hello-count-tick",
        coalesce=True,
        max_instances=1,
    )
