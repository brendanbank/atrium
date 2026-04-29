# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Admin API for the email outbox.

Two endpoints to pin:

* ``GET /admin/email-outbox`` — paginated list with optional status
  filter, gated on ``email_outbox.manage``.
* ``POST /admin/email-outbox/{id}/drain`` — synchronous send, refuses
  non-pending rows with 409, writes an audit row.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.email.sender import enqueue_and_log
from app.models.email_outbox import EmailOutbox
from app.models.ops import AuditLog
from tests.helpers import login, seed_admin, seed_user

_INVITE_CONTEXT = {
    "invited_by_name": "Alice",
    "accept_url": "https://example.com/x",
    "expires_on": "tomorrow",
}


async def _enqueue(engine, *, to: str = "guest@example.com") -> EmailOutbox:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        rows = await enqueue_and_log(
            s,
            template="invite",
            to=[to],
            context=_INVITE_CONTEXT,
        )
        await s.commit()
        return rows[0]


@pytest.mark.asyncio
async def test_list_requires_email_outbox_manage(client, engine):
    user = await seed_user(engine)
    await login(client, user.email, "user-pw-123", engine=engine)
    r = await client.get("/admin/email-outbox")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_list_outbox(client, engine):
    await _enqueue(engine, to="a@example.com")
    await _enqueue(engine, to="b@example.com")
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)

    r = await client.get("/admin/email-outbox")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 2
    addrs = {row["to_addr"] for row in body["items"]}
    assert {"a@example.com", "b@example.com"}.issubset(addrs)
    # The ``context`` JSON intentionally isn't returned.
    for row in body["items"]:
        assert "context" not in row
        assert row["status"] in {"pending", "sending", "sent", "dead"}


@pytest.mark.asyncio
async def test_list_filters_by_status(client, engine):
    pending = await _enqueue(engine, to="p@example.com")
    sent = await _enqueue(engine, to="s@example.com")

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        row = (await s.execute(
            select(EmailOutbox).where(EmailOutbox.id == sent.id)
        )).scalar_one()
        row.status = "sent"
        await s.commit()

    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)
    r = await client.get("/admin/email-outbox", params={"status": "pending"})
    assert r.status_code == 200, r.text
    ids = {row["id"] for row in r.json()["items"]}
    assert pending.id in ids
    assert sent.id not in ids

    r = await client.get("/admin/email-outbox", params={"status": "sent"})
    ids = {row["id"] for row in r.json()["items"]}
    assert sent.id in ids
    assert pending.id not in ids


@pytest.mark.asyncio
async def test_list_rejects_unknown_status(client, engine):
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)
    r = await client.get("/admin/email-outbox", params={"status": "weird"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_drain_sends_pending_row(client, engine, monkeypatch):
    sent: list[dict] = []

    class _RecordingBackend:
        name = "recording"

        async def send(self, message):
            sent.append({"to": list(message.to), "subject": message.subject})

    monkeypatch.setattr(
        "app.jobs.builtin_handlers.get_mail_backend", lambda: _RecordingBackend()
    )

    outbox = await _enqueue(engine, to="drain@example.com")
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)

    r = await client.post(f"/admin/email-outbox/{outbox.id}/drain")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == outbox.id
    assert body["status"] == "sent"
    assert body["attempts"] == 1
    assert body["last_error"] is None
    assert len(sent) == 1
    assert sent[0]["to"] == ["drain@example.com"]

    # Audit row written under the actor's id, action="drain".
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        rows = (await s.execute(
            select(AuditLog)
            .where(
                AuditLog.entity == "email_outbox",
                AuditLog.entity_id == outbox.id,
                AuditLog.action == "drain",
            )
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].actor_user_id == admin.id


@pytest.mark.asyncio
async def test_drain_transient_failure_returns_pending(
    client, engine, monkeypatch
):
    class _BrokenBackend:
        name = "broken"

        async def send(self, message):
            raise ConnectionError("relay down")

    monkeypatch.setattr(
        "app.jobs.builtin_handlers.get_mail_backend", lambda: _BrokenBackend()
    )

    outbox = await _enqueue(engine, to="fail@example.com")
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)

    r = await client.post(f"/admin/email-outbox/{outbox.id}/drain")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["attempts"] == 1
    assert "ConnectionError" in (body["last_error"] or "")


@pytest.mark.asyncio
async def test_drain_refuses_already_sent_row(client, engine):
    outbox = await _enqueue(engine, to="done@example.com")

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        row = (await s.execute(
            select(EmailOutbox).where(EmailOutbox.id == outbox.id)
        )).scalar_one()
        row.status = "sent"
        await s.commit()

    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)

    r = await client.post(f"/admin/email-outbox/{outbox.id}/drain")
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_drain_404_on_missing(client, engine):
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)
    r = await client.post("/admin/email-outbox/9999999/drain")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_drain_requires_email_outbox_manage(client, engine):
    outbox = await _enqueue(engine, to="x@example.com")
    user = await seed_user(engine)
    await login(client, user.email, "user-pw-123", engine=engine)
    r = await client.post(f"/admin/email-outbox/{outbox.id}/drain")
    assert r.status_code == 403
