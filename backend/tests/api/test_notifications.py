# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""End-to-end coverage for the notification surface.

Atrium ships:

- ``services.notifications.notify_user`` — slim helper: add a row,
  publish the matching ``{kind, payload}`` event on the SSE pub/sub.
- ``/notifications`` — list, unread count, mark-read, mark-all-read,
  delete, SSE stream.

Tests verify the helper writes through the active session, that
endpoints are scoped to the calling user (no cross-user leakage), and
that the helper publishes the typed event on the in-process
``event_hub`` so the SSE bell refetches and host bundles can route on
the kind.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.ops import Notification
from app.services.event_hub import hub
from app.services.notifications import notify_user
from tests.helpers import login, seed_admin, seed_user


@pytest.mark.asyncio
async def test_notify_user_writes_row_and_publishes_event(client, engine):
    # ``client`` is taken purely so the conftest's truncate-on-teardown
    # fires; the test itself drives the helper directly.
    _ = client
    admin = await seed_admin(engine)

    queue = hub.subscribe(admin.id)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            notify_user(
                session,
                user_id=admin.id,
                kind="welcome",
                payload={"hello": "there"},
            )
            await session.commit()

            row = (
                await session.execute(
                    select(Notification).where(Notification.user_id == admin.id)
                )
            ).scalar_one()
            assert row.kind == "welcome"
            assert row.payload == {"hello": "there"}
            assert row.read_at is None

        # The helper also pokes event_hub so the SSE bell refetches and
        # host bundles can route the typed event to selective query
        # invalidations. The published payload mirrors the row.
        event = await queue.get()
        assert event == {"kind": "welcome", "payload": {"hello": "there"}}
    finally:
        hub.unsubscribe(admin.id, queue)


@pytest.mark.asyncio
async def test_notify_user_does_not_commit(client, engine):
    """Caller controls the transaction. If the surrounding work rolls
    back, the notification row must vanish with it."""
    _ = client  # only here for the truncate-on-teardown
    admin = await seed_admin(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        notify_user(
            session,
            user_id=admin.id,
            kind="will-be-rolled-back",
            payload={"x": 1},
        )
        await session.rollback()

    async with factory() as session:
        rows = (
            await session.execute(
                select(Notification).where(Notification.user_id == admin.id)
            )
        ).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_list_endpoint_scopes_to_caller(client, engine):
    """One user's notifications must never appear in another's list."""
    admin = await seed_admin(engine)
    other = await seed_user(engine)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        notify_user(session, user_id=admin.id, kind="for-admin", payload={})
        notify_user(session, user_id=other.id, kind="for-other", payload={})
        await session.commit()

    await login(client, admin.email, "admin-pw-123", engine=engine)
    r = await client.get("/notifications")
    assert r.status_code == 200
    kinds = {row["kind"] for row in r.json()}
    assert kinds == {"for-admin"}


@pytest.mark.asyncio
async def test_unread_count_only_counts_unread(client, engine):
    admin = await seed_admin(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        notify_user(session, user_id=admin.id, kind="a", payload={})
        notify_user(session, user_id=admin.id, kind="b", payload={})
        notify_user(session, user_id=admin.id, kind="c", payload={})
        await session.commit()

    await login(client, admin.email, "admin-pw-123", engine=engine)
    r = await client.get("/notifications/unread-count")
    assert r.status_code == 200
    assert r.json()["count"] == 3

    rows = (await client.get("/notifications")).json()
    target_id = rows[0]["id"]
    await client.post(f"/notifications/{target_id}/read")

    r = await client.get("/notifications/unread-count")
    assert r.json()["count"] == 2


@pytest.mark.asyncio
async def test_mark_read_is_idempotent_and_sticky(client, engine):
    """Reading a row twice keeps the original timestamp; reading
    someone else's row 404s rather than silently no-oping."""
    admin = await seed_admin(engine)
    other = await seed_user(engine)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        notify_user(session, user_id=admin.id, kind="mine", payload={})
        notify_user(session, user_id=other.id, kind="not-mine", payload={})
        await session.commit()
        admin_id = (
            await session.execute(
                select(Notification.id).where(Notification.user_id == admin.id)
            )
        ).scalar_one()
        other_id = (
            await session.execute(
                select(Notification.id).where(Notification.user_id == other.id)
            )
        ).scalar_one()

    await login(client, admin.email, "admin-pw-123", engine=engine)
    r1 = await client.post(f"/notifications/{admin_id}/read")
    assert r1.status_code == 200
    first_read_at = datetime.fromisoformat(r1.json()["read_at"])

    r2 = await client.post(f"/notifications/{admin_id}/read")
    assert r2.status_code == 200
    # Idempotent: handler is a no-op on the second call, so the
    # timestamp doesn't drift to "now". MySQL DATETIME(0) rounds the
    # initial write half-up, which can shift the value by up to ~1s
    # vs. the in-memory Python datetime in r1, so we allow 2s of slack
    # rather than strict equality (see CLAUDE.md gotcha #1).
    second_read_at = datetime.fromisoformat(r2.json()["read_at"])
    assert abs((second_read_at - first_read_at).total_seconds()) <= 2

    # Trying to read someone else's notification is a 404 (not 403) so
    # the existence of foreign rows isn't disclosed.
    r3 = await client.post(f"/notifications/{other_id}/read")
    assert r3.status_code == 404


@pytest.mark.asyncio
async def test_mark_all_read_zeroes_the_counter(client, engine):
    admin = await seed_admin(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        for kind in ("a", "b", "c"):
            notify_user(session, user_id=admin.id, kind=kind, payload={})
        await session.commit()

    await login(client, admin.email, "admin-pw-123", engine=engine)
    assert (await client.get("/notifications/unread-count")).json()["count"] == 3

    r = await client.post("/notifications/mark-all-read")
    assert r.status_code == 200
    assert r.json()["count"] == 0
    assert (await client.get("/notifications/unread-count")).json()["count"] == 0


@pytest.mark.asyncio
async def test_delete_removes_only_callers_row(client, engine):
    admin = await seed_admin(engine)
    other = await seed_user(engine)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        notify_user(session, user_id=admin.id, kind="mine", payload={})
        notify_user(session, user_id=other.id, kind="not-mine", payload={})
        await session.commit()
        admin_id = (
            await session.execute(
                select(Notification.id).where(Notification.user_id == admin.id)
            )
        ).scalar_one()
        other_id = (
            await session.execute(
                select(Notification.id).where(Notification.user_id == other.id)
            )
        ).scalar_one()

    await login(client, admin.email, "admin-pw-123", engine=engine)
    r = await client.delete(f"/notifications/{admin_id}")
    assert r.status_code == 204

    # Foreign id 404s.
    r = await client.delete(f"/notifications/{other_id}")
    assert r.status_code == 404

    # Other user's row survives.
    async with factory() as session:
        survivor = (
            await session.execute(
                select(Notification).where(Notification.id == other_id)
            )
        ).scalar_one_or_none()
        assert survivor is not None


@pytest.mark.asyncio
async def test_unread_only_filter(client, engine):
    admin = await seed_admin(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        notify_user(session, user_id=admin.id, kind="will-mark", payload={})
        notify_user(session, user_id=admin.id, kind="will-leave", payload={})
        await session.commit()

    await login(client, admin.email, "admin-pw-123", engine=engine)
    rows = (await client.get("/notifications")).json()
    mark_id = next(r["id"] for r in rows if r["kind"] == "will-mark")
    await client.post(f"/notifications/{mark_id}/read")

    only_unread = (
        await client.get("/notifications", params={"unread_only": "true"})
    ).json()
    assert {r["kind"] for r in only_unread} == {"will-leave"}


# ---- SSE stream connection-pool behaviour (issue #246) -----------------


async def _drive_sse_stream(asgi_app, cookie_header: str):
    """Open ``/notifications/stream`` over raw ASGI and return once the
    first body chunk has been pushed, leaving the stream open.

    httpx's ``ASGITransport`` joins the whole body before handing back a
    response, so it can never see a live SSE stream -- it would block
    forever. Driving the ASGI callable directly is the only way to
    observe the server while the connection is still open.

    Returns ``(task, disconnect_event, first_chunk_event, pool_samples)``.
    The caller must set ``disconnect_event`` and await ``task``.
    """
    disconnect = asyncio.Event()
    first_chunk = asyncio.Event()

    async def receive():
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body" and message.get("body"):
            first_chunk.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "path": "/notifications/stream",
        "raw_path": b"/notifications/stream",
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "server": ("test", 80),
        "client": ("127.0.0.1", 123),
        "headers": [
            (b"host", b"test"),
            (b"cookie", cookie_header.encode()),
        ],
    }

    task = asyncio.create_task(asgi_app(scope, receive, send))
    await asyncio.wait_for(first_chunk.wait(), timeout=15)
    return task, disconnect


@pytest.mark.asyncio
async def test_sse_stream_does_not_pin_a_pooled_connection(
    client, asgi_app, engine
):
    """A live SSE stream must hold zero pooled DB connections.

    ``Depends(current_user)`` resolves ``get_session``, and FastAPI
    defers yield-dependency teardown until the response body is fully
    sent -- which for an SSE stream is "when the tab closes". That
    pinned one connection per open stream and drained the pool with a
    handful of tabs (issue #246). The stream body itself never touches
    the database, so the correct steady state is zero.
    """
    await seed_admin(engine)
    await login(client, "admin@example.com", "admin-pw-123", engine=engine)
    cookie_header = "; ".join(f"{k}={v}" for k, v in client.cookies.items())

    pool = engine.sync_engine.pool
    assert pool.checkedout() == 0, "pool not idle before the stream opened"

    task, disconnect = await _drive_sse_stream(asgi_app, cookie_header)
    try:
        assert pool.checkedout() == 0, (
            "the open SSE stream is holding a pooled connection"
        )
    finally:
        disconnect.set()
        await asyncio.wait_for(task, timeout=15)


@pytest.mark.asyncio
async def test_sse_stream_still_rejects_an_unauthenticated_caller(
    client, asgi_app, engine
):
    """Releasing the session early must not weaken the auth gate."""
    _ = client
    _ = engine
    statuses: list[int] = []

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            statuses.append(message["status"])

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "path": "/notifications/stream",
        "raw_path": b"/notifications/stream",
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "server": ("test", 80),
        "client": ("127.0.0.1", 123),
        "headers": [(b"host", b"test")],
    }

    await asyncio.wait_for(asgi_app(scope, receive, send), timeout=15)
    assert statuses == [401]
