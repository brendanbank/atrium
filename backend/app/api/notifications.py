# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Notifications API for the bell icon in the header.

Each user only sees their own notifications. Atrium ships the
endpoints (list, mark read, unread count, SSE stream) but no built-in
emitters — host apps call ``app.services.notifications.notify_user``
from their own flows to populate rows.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.users import current_user
from app.db import get_session
from app.logging import log
from app.models.auth import User
from app.models.ops import Notification
from app.schemas.notification import NotificationRead, UnreadCount
from app.services.event_hub import hub

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@router.get("", response_model=list[NotificationRead])
async def list_notifications(
    user: User = Depends(current_user),
    limit: int = Query(default=50, ge=1, le=200),
    unread_only: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> list[Notification]:
    stmt = (
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    return list((await session.execute(stmt)).scalars().all())


@router.get("/unread-count", response_model=UnreadCount)
async def unread_count(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> UnreadCount:
    n = (
        await session.execute(
            select(func.count(Notification.id)).where(
                Notification.user_id == user.id,
                Notification.read_at.is_(None),
            )
        )
    ).scalar_one()
    return UnreadCount(count=int(n or 0))


@router.post("/{notification_id}/read", response_model=NotificationRead)
async def mark_read(
    notification_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Notification:
    n = await session.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if n.read_at is None:
        n.read_at = _utcnow_naive()
        await session.commit()
    return n


@router.post("/mark-all-read", response_model=UnreadCount)
async def mark_all_read(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> UnreadCount:
    await session.execute(
        update(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.read_at.is_(None),
        )
        .values(read_at=_utcnow_naive())
    )
    await session.commit()
    return UnreadCount(count=0)


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notification_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    n = await session.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await session.delete(n)
    await session.commit()


# ---- Server-Sent Events stream ----------------------------------------


# Shorter than any plausible intermediate-proxy idle timeout — Caddy's
# and Cloudflare's defaults sit at 60s+, bumping our own keepalive to
# 15s gives the connection a comfortable margin.
_STREAM_KEEPALIVE_SECONDS = 15


@router.get("/stream")
async def notifications_stream(
    request: Request,
    user: User = Depends(current_user),
):
    """One-way server push so the bell updates without polling.

    The event payload is intentionally minimal — the presence of the
    message is the signal; the client refetches /notifications and
    /unread-count to get the real state. Keeps the wire format simple
    and side-steps ordering/consistency concerns.
    """
    queue = hub.subscribe(user.id)
    log.info("sse.stream.open", user_id=user.id, subs=len(hub._subs.get(user.id, ())))

    async def event_source():
        # Initial "hello" so the client knows the stream is alive —
        # browsers show network activity before the first real event.
        # ``retry:`` tells EventSource to reconnect in 2s instead of
        # its 3s default if the stream drops.
        yield "retry: 2000\nevent: ready\ndata: {}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    log.info("sse.stream.disconnect", user_id=user.id)
                    return
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=_STREAM_KEEPALIVE_SECONDS
                    )
                except TimeoutError:
                    # Periodic comment line keeps proxies from closing
                    # the long-lived connection on idle timeout.
                    yield ": keepalive\n\n"
                    continue
                yield f"event: notification\ndata: {json.dumps(event)}\n\n"
        finally:
            hub.unsubscribe(user.id, queue)
            log.info("sse.stream.close", user_id=user.id)

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            # Tell Traefik / nginx to not buffer.
            "X-Accel-Buffering": "no",
        },
    )
