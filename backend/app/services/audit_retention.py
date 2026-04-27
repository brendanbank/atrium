# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Audit-log retention pruning.

Atrium keeps an unbounded ``audit_log`` by default. Operators that need
GDPR-style time-bounded retention enable it by writing
``app_settings['audit'] = {"retention_days": N}`` (N > 0). The
``audit_prune`` scheduled job reads that setting and calls the helper
below daily.

A single parameterised DELETE relies on MySQL's server-side ``NOW()``
so we don't have to ship a Python timestamp across the wire. The
``retention_days <= 0`` branch is the explicit "keep forever" sentinel
the admin UI exposes.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def prune_audit_log(session: AsyncSession, retention_days: int) -> int:
    """Delete ``audit_log`` rows older than ``retention_days`` days.

    Returns the number of rows deleted. ``retention_days <= 0`` is the
    "retain forever" sentinel and short-circuits to 0.
    """
    if retention_days <= 0:
        return 0

    result = await session.execute(
        text(
            "DELETE FROM audit_log "
            "WHERE created_at < NOW() - INTERVAL :days DAY"
        ),
        {"days": retention_days},
    )
    await session.commit()
    return result.rowcount or 0
