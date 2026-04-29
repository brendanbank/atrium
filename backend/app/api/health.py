# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Service health probes.

- ``/healthz``   — liveness. api process answers → 200.
- ``/readyz``   — readiness. api + MySQL round-trip.
- ``/health``   — aggregate. Verifies the runtime services
  (api implicit, MySQL, worker) in parallel. Returns a plain-
  text ``OK\\n`` with HTTP 200 when every probe passes; 503 with a
  machine-readable failure list otherwise. Shape matches the
  ``dyndns-route53`` monitoring convention so external uptime tools
  can hit it without special-casing.

  No separate web check: the SPA is served by this same api process
  via Starlette StaticFiles, so api liveness already implies the SPA
  is reachable.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.ops import AppSetting

router = APIRouter(tags=["health"])

# Matches worker.py:HEARTBEAT_KEY. Duplicated literal rather than a
# cross-module import because this file is in the hot path for external
# probes and should stay dependency-light.
_HEARTBEAT_KEY = "worker_heartbeat"

# Worker writes every 30s; 120s leaves room for a missed tick + GC pause
# before we flip to 503. Tuned against the HEARTBEAT_INTERVAL_SECONDS in
# app/worker.py — bump both together.
_HEARTBEAT_MAX_AGE_SECONDS = 120


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - error path exercised by integration tests
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"db unavailable: {exc.__class__.__name__}",
        ) from exc
    return {"status": "ready"}


async def _check_mysql(session: AsyncSession) -> str | None:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        # Class name only — exception payloads can echo connection
        # strings, host:port pairs or stack frames into a public probe.
        return exc.__class__.__name__
    return None


async def _check_worker(session: AsyncSession) -> str | None:
    row = (
        await session.execute(
            select(AppSetting.value).where(AppSetting.key == _HEARTBEAT_KEY)
        )
    ).scalar_one_or_none()
    if row is None:
        return "no heartbeat recorded"
    ts_raw = row.get("ts") if isinstance(row, dict) else None
    if not ts_raw:
        return "malformed heartbeat payload"
    try:
        ts = datetime.fromisoformat(ts_raw)
    except ValueError:
        return "unparseable heartbeat ts"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    age = (datetime.now(UTC) - ts).total_seconds()
    if age > _HEARTBEAT_MAX_AGE_SECONDS:
        return f"stale heartbeat (last {int(age)}s ago)"
    return None


@router.get("/health", response_class=PlainTextResponse)
async def health(
    session: AsyncSession = Depends(get_session),
) -> PlainTextResponse:
    """All runtime services green, or 503 with failure list.

    Runs every probe even after an earlier failure so the response
    body names every broken service at once — easier to debug a
    page than re-probing to find the second cause. Sequential (not
    gather) because the mysql + worker probes share one AsyncSession
    and SQLAlchemy async sessions aren't safe for concurrent use.
    """
    mysql_err = await _check_mysql(session)
    worker_err = await _check_worker(session)
    failures = []
    if mysql_err:
        failures.append(f"mysql: {mysql_err}")
    if worker_err:
        failures.append(f"worker: {worker_err}")

    if failures:
        body = "\n".join(failures) + "\n"
        return PlainTextResponse(
            content=body, status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    return PlainTextResponse(content="OK\n")
