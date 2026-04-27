# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Thin helper for writing audit_log rows.

Callers don't commit — the audit entry travels in the same transaction
as the change it describes, so if the change rolls back the audit
entry does too.

The diff payload goes into a JSON column, so every value must be
JSON-serialisable. We coerce date/datetime/Decimal/Enum recursively
here so callers can pass through Pydantic/SQLAlchemy values directly
without worrying about the column's encoder.

Impersonation: when a super_admin session has a valid
``atrium_impersonator`` cookie, a middleware populates
``_impersonator_user_id`` (a ContextVar) for the request, and
``record`` writes it to the ``impersonator_user_id`` column. Callers
never need to pass it explicitly — 40-odd call sites would be a lot
of boilerplate. The middleware lives in ``app.main``.
"""
from __future__ import annotations

from contextvars import ContextVar
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ops import AuditLog

_impersonator_user_id: ContextVar[int | None] = ContextVar(
    "atrium_audit_impersonator_user_id", default=None
)


def set_impersonator(user_id: int | None) -> None:
    """Middleware-only entry point: pin the impersonator id for the
    current request. Cleared (set to None) after the response goes out."""
    _impersonator_user_id.set(user_id)


def get_impersonator() -> int | None:
    return _impersonator_user_id.get()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        # Best-effort: render as a string to avoid float imprecision.
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    # Last resort: str() — safer than letting json.dumps raise inside
    # the SQLAlchemy flush, which rolls back the whole transaction.
    return str(value)


async def record(
    session: AsyncSession,
    *,
    actor_user_id: int | None,
    entity: str,
    entity_id: int,
    action: str,
    diff: dict[str, Any] | None = None,
) -> None:
    safe_diff: dict[str, Any] | None = (
        _json_safe(diff) if diff is not None else None
    )
    session.add(
        AuditLog(
            actor_user_id=actor_user_id,
            impersonator_user_id=_impersonator_user_id.get(),
            entity=entity,
            entity_id=entity_id,
            action=action,
            diff=safe_diff,
        )
    )
