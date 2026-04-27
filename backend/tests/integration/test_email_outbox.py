# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Email outbox queue — enqueue + handler retry behaviour.

The outbox is the durable side of the email send path. ``enqueue_and_log``
inserts pending rows; the worker tick converts due rows into
``scheduled_jobs`` rows; ``email_send_handler`` drains a single row
with exponential backoff on failure and dead-letters at attempt 6.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.email.sender import enqueue_and_log
from app.jobs.builtin_handlers import (
    MAX_ATTEMPTS,
    email_send_handler,
)
from app.models.email_outbox import EmailOutbox
from app.models.enums import EmailStatus, JobState
from app.models.ops import EmailLog, ScheduledJob


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _make_job(session: AsyncSession, outbox_id: int) -> ScheduledJob:
    """Stand-in for what _drain_outbox would create at the worker tick."""
    job = ScheduledJob(
        job_type="email_send",
        run_at=_utcnow_naive(),
        state=JobState.PENDING.value,
        payload={"outbox_id": outbox_id},
    )
    session.add(job)
    await session.flush()
    return job


async def test_enqueue_and_log_writes_outbox_and_email_log(session: AsyncSession):
    rows = await enqueue_and_log(
        session,
        template="invite",
        to=["a@example.com", "b@example.com"],
        context={"invited_by_name": "Alice", "accept_url": "https://x", "expires_on": "tomorrow"},
        entity_type="invite",
        entity_id=42,
    )
    await session.commit()

    assert len(rows) == 2
    addrs = sorted(r.to_addr for r in rows)
    assert addrs == ["a@example.com", "b@example.com"]
    for r in rows:
        assert r.template == "invite"
        assert r.status == "pending"
        assert r.attempts == 0
        assert r.entity_type == "invite"
        assert r.entity_id == 42

    logs = (
        await session.execute(
            select(EmailLog).where(EmailLog.template == "invite").order_by(EmailLog.id)
        )
    ).scalars().all()
    assert len(logs) == 2
    for log_row in logs:
        assert log_row.status == EmailStatus.QUEUED.value
        assert log_row.entity_type == "invite"
        assert log_row.entity_id == 42


async def test_enqueue_rejects_unknown_template(session: AsyncSession):
    with pytest.raises(LookupError):
        await enqueue_and_log(
            session,
            template="does_not_exist",
            to=["x@example.com"],
            context={},
        )


async def test_handler_success_marks_sent_and_logs(
    session: AsyncSession, monkeypatch
):
    sent: list[dict] = []

    class _RecordingBackend:
        name = "recording"

        async def send(self, message):
            sent.append({"to": list(message.to), "subject": message.subject})

    monkeypatch.setattr(
        "app.jobs.builtin_handlers.get_mail_backend", lambda: _RecordingBackend()
    )

    rows = await enqueue_and_log(
        session,
        template="invite",
        to=["guest@example.com"],
        context={"invited_by_name": "Alice", "accept_url": "https://x", "expires_on": "tomorrow"},
    )
    await session.commit()
    outbox = rows[0]

    job = await _make_job(session, outbox.id)
    await session.commit()

    await email_send_handler(session, job, {"outbox_id": outbox.id})
    await session.commit()

    refreshed = (
        await session.execute(select(EmailOutbox).where(EmailOutbox.id == outbox.id))
    ).scalar_one()
    assert refreshed.status == "sent"
    assert refreshed.attempts == 1
    assert refreshed.last_error is None

    assert len(sent) == 1
    assert sent[0]["to"] == ["guest@example.com"]
    assert sent[0]["subject"]  # rendered (non-empty) Jinja subject

    sent_logs = (
        await session.execute(
            select(EmailLog)
            .where(
                EmailLog.template == "invite",
                EmailLog.status == EmailStatus.SENT.value,
            )
        )
    ).scalars().all()
    assert len(sent_logs) == 1
    assert sent_logs[0].to_addr == "guest@example.com"


async def test_handler_transient_failure_schedules_backoff(
    session: AsyncSession, monkeypatch
):
    class _BrokenBackend:
        name = "broken"

        async def send(self, message):
            raise ConnectionError("relay down")

    monkeypatch.setattr(
        "app.jobs.builtin_handlers.get_mail_backend", lambda: _BrokenBackend()
    )

    rows = await enqueue_and_log(
        session,
        template="invite",
        to=["guest@example.com"],
        context={"invited_by_name": "Alice", "accept_url": "https://x", "expires_on": "tomorrow"},
    )
    await session.commit()
    outbox = rows[0]
    job = await _make_job(session, outbox.id)
    await session.commit()

    before = _utcnow_naive()
    await email_send_handler(session, job, {"outbox_id": outbox.id})
    await session.commit()

    refreshed = (
        await session.execute(select(EmailOutbox).where(EmailOutbox.id == outbox.id))
    ).scalar_one()
    assert refreshed.status == "pending"
    assert refreshed.attempts == 1
    assert "ConnectionError" in (refreshed.last_error or "")
    # First-failure backoff is 60s; allow some clock slack.
    assert refreshed.next_attempt_at >= before + timedelta(seconds=55)
    assert refreshed.next_attempt_at <= before + timedelta(seconds=120)


async def test_handler_dead_letters_after_max_attempts(
    session: AsyncSession, monkeypatch
):
    class _BrokenBackend:
        name = "broken"

        async def send(self, message):
            raise RuntimeError("permanently broken")

    monkeypatch.setattr(
        "app.jobs.builtin_handlers.get_mail_backend", lambda: _BrokenBackend()
    )

    rows = await enqueue_and_log(
        session,
        template="invite",
        to=["guest@example.com"],
        context={"invited_by_name": "Alice", "accept_url": "https://x", "expires_on": "tomorrow"},
    )
    await session.commit()
    outbox = rows[0]

    # Fast-forward to just before the dead-letter threshold so the next
    # failure trips ``status=dead`` without grinding through five real
    # waits. attempts is incremented inside the handler, so seeding
    # MAX_ATTEMPTS-1 means the about-to-happen failure becomes the
    # MAX_ATTEMPTS-th.
    await session.execute(
        text("UPDATE email_outbox SET attempts = :n WHERE id = :id"),
        {"n": MAX_ATTEMPTS - 1, "id": outbox.id},
    )
    await session.commit()
    # The SQL UPDATE bypassed the identity map; force the in-memory
    # row to re-read so the handler sees attempts=MAX_ATTEMPTS-1.
    await session.refresh(outbox)

    job = await _make_job(session, outbox.id)
    await session.commit()

    await email_send_handler(session, job, {"outbox_id": outbox.id})
    await session.commit()

    refreshed = (
        await session.execute(select(EmailOutbox).where(EmailOutbox.id == outbox.id))
    ).scalar_one()
    assert refreshed.status == "dead"
    assert refreshed.attempts == MAX_ATTEMPTS

    failed_logs = (
        await session.execute(
            select(EmailLog).where(
                EmailLog.template == "invite",
                EmailLog.status == EmailStatus.FAILED.value,
            )
        )
    ).scalars().all()
    assert len(failed_logs) == 1
    assert failed_logs[0].to_addr == "guest@example.com"
