"""Built-in scheduled-job handlers.

Atrium ships a thin layer of platform-level handlers (audit-log
retention, email send, ...). Host apps register their own domain
handlers separately via ``app.jobs.runner.register_handler``.

The worker calls :func:`register_builtin_handlers` once at startup.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.runner import register_handler
from app.logging import log
from app.models.ops import AppSetting, ScheduledJob
from app.services.audit_retention import prune_audit_log


async def audit_prune_handler(
    session: AsyncSession,
    job: ScheduledJob,
    payload: dict[str, Any],
) -> None:
    """Read the ``audit`` setting and prune the audit log accordingly.

    Missing setting row → retention_days defaults to 0 (forever) and the
    helper short-circuits without touching the table.
    """
    del job, payload  # handler is configured globally, not per-row

    raw = (
        await session.execute(
            select(AppSetting.value).where(AppSetting.key == "audit")
        )
    ).scalar_one_or_none()
    retention_days = int((raw or {}).get("retention_days", 0))

    deleted = await prune_audit_log(session, retention_days)
    log.info("audit.pruned", count=deleted, retention_days=retention_days)


def register_builtin_handlers() -> None:
    """Register every platform-owned handler with the runner."""
    register_handler("audit_prune", audit_prune_handler)
