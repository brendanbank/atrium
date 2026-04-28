# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Host-side worker context.

Atrium hands one of these to a host's ``init_worker(host)`` so the host
can register APScheduler jobs and ``scheduled_jobs`` handlers through a
typed surface — the worker-side equivalent of the frontend's six
``__ATRIUM_REGISTRY__.register*`` methods. Hosts no longer need to
import ``app.jobs.runner.register_handler`` directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.jobs.runner import JobHandler, register_handler
from app.logging import log


@dataclass
class HostWorkerCtx:
    """Typed surface passed to a host's ``init_worker(host)`` callback.

    The dataclass is the extension point: future host-facing worker
    capabilities (e.g. a richer ``register_periodic`` helper, scheduler
    introspection) get added as new attributes without churning the
    callback signature.
    """

    scheduler: AsyncIOScheduler
    """The APScheduler instance atrium runs platform ticks against.

    Hosts call ``host.scheduler.add_job(...)`` for recurring inline
    work; for durable, atomic, queue-backed work use
    :meth:`register_job_handler` and insert ``scheduled_jobs`` rows."""

    _registered_kinds: set[str] = field(default_factory=set, repr=False)

    def register_job_handler(
        self,
        *,
        kind: str,
        handler: JobHandler,
        description: str | None = None,
    ) -> None:
        """Register ``handler`` to drain ``scheduled_jobs`` rows of
        ``job_type=kind``.

        ``handler`` is ``async (session, job, payload) -> None``. The
        runner already wraps every invocation in a try/except (see
        ``app.jobs.runner.run_one``) — a thrower marks the row FAILED
        and is logged as ``job.failed`` rather than killing the worker.
        That mirrors the frontend ``subscribeEvent`` fan-out: one bad
        handler can't bring the loop down.

        ``description`` is a short human-readable label (used in
        startup logs and, eventually, ``/admin/jobs`` introspection).

        Re-registering the same ``kind`` is allowed (last-write-wins,
        matching ``register_handler``) but emits a ``warning`` log so
        an accidental collision is visible.
        """
        if not kind:
            raise ValueError("register_job_handler: 'kind' must be non-empty")
        if kind in self._registered_kinds:
            log.warning(
                "host.job_handler.duplicate",
                kind=kind,
                description=description,
            )
        register_handler(kind, handler)
        self._registered_kinds.add(kind)
        log.info(
            "host.job_handler.registered",
            kind=kind,
            description=description,
        )


__all__ = ["HostWorkerCtx", "JobHandler"]
