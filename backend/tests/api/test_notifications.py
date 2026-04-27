# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""End-to-end coverage for the notification surface.

Atrium ships:

- ``services.notifications.notify_user`` — slim helper: add a row,
  publish a refresh event on the SSE pub/sub.
- ``/notifications`` — list, unread count, mark-read, mark-all-read,
  delete, SSE stream.

Tests verify the helper writes through the active session, that
endpoints are scoped to the calling user (no cross-user leakage), and
that the helper publishes to the in-process ``event_hub`` so the SSE
bell refetches.
"""
from __future__ import annotations

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

        # The helper also pokes event_hub so the SSE bell refetches.
        event = await queue.get()
        assert event == {"kind": "refresh"}
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
