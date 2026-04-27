# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Built-in scheduled-job handlers shipped with Atrium.

Most platform-level work belongs in host apps (atrium ships the queue
plumbing, not domain handlers), but a handful of jobs are part of the
platform itself:

* ``audit_prune`` — daily DELETE on ``audit_log`` driven by the
  ``audit.retention_days`` app setting.
* ``email_send`` — drains the durable ``email_outbox`` queue with
  exponential backoff. The outbox itself is owned by atrium so its
  handler is too.

The worker calls :func:`register_builtin_handlers` once at startup.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.email.backend import EmailMessage, get_mail_backend
from app.email.sender import render_template
from app.jobs.runner import register_handler
from app.logging import log
from app.models.auth import User
from app.models.email_outbox import EmailOutbox
from app.models.enums import EmailStatus
from app.models.ops import AppSetting, EmailLog, ScheduledJob
from app.services.audit_retention import prune_audit_log


def _utcnow_naive() -> datetime:
    """MySQL DATETIME columns here are naive — strip tz for comparisons."""
    return datetime.now(UTC).replace(tzinfo=None)


# ----- audit retention -----


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


# ----- email outbox -----


# Backoff schedule indexed by attempts after the failed try (1-based).
# After the 1st failure wait 60s, 2nd 5min, 3rd 30min, 4th 2h, 5th 12h.
# A 6th failure trips dead-letter — see MAX_ATTEMPTS.
_BACKOFF_SECONDS: tuple[int, ...] = (60, 300, 1800, 7200, 43200)
MAX_ATTEMPTS = 6


def _backoff_delta(attempts: int) -> timedelta:
    # ``attempts`` is the count of tries already taken (>=1 by the time
    # we're scheduling a retry). Clamp into the table to keep things
    # well-defined past index 5 (only matters if MAX_ATTEMPTS grows).
    idx = min(max(attempts - 1, 0), len(_BACKOFF_SECONDS) - 1)
    return timedelta(seconds=_BACKOFF_SECONDS[idx])


async def email_send_handler(
    session: AsyncSession,
    job: ScheduledJob,
    payload: dict[str, Any],
) -> None:
    """Drain a single ``email_outbox`` row.

    Locks the row FOR UPDATE, attempts delivery via the configured mail
    backend, and either marks it ``sent``, schedules a backoff retry,
    or moves it to ``dead`` after ``MAX_ATTEMPTS`` failures. A final
    ``email_log`` row is written on terminal states so the admin mail
    log mirrors what really happened.
    """
    outbox_id = payload.get("outbox_id")
    if not isinstance(outbox_id, int):
        raise ValueError(f"email_send: payload missing 'outbox_id': {payload!r}")

    stmt = (
        select(EmailOutbox)
        .where(EmailOutbox.id == outbox_id)
        .with_for_update()
    )
    outbox = (await session.execute(stmt)).scalar_one_or_none()
    if outbox is None:
        # The row was deleted (admin cleanup, manual SQL) — nothing to do.
        log.warning("email_outbox.missing", outbox_id=outbox_id, job_id=job.id)
        return

    if outbox.status in {"sent", "dead"}:
        # Idempotent: a prior attempt already finalised this row. The
        # outbox-drain tick is best-effort dedupe but a race is possible.
        return

    outbox.status = "sending"
    outbox.attempts = (outbox.attempts or 0) + 1
    # Flush so the row visibly progresses even if the handler later
    # raises — the runner's outer commit will persist it. The
    # FOR UPDATE lock above already serialises competing workers; we
    # don't need a discrete inner commit for that.
    await session.flush()

    try:
        subject, text, html = await render_template(
            session, outbox.template, outbox.context, outbox.locale or "en"
        )
        backend = get_mail_backend()
        await backend.send(
            EmailMessage(
                to=[outbox.to_addr],
                subject=subject,
                body_text=text,
                body_html=html,
                template=outbox.template,
            )
        )
    except Exception as exc:
        error = f"{exc.__class__.__name__}: {exc}"
        log.warning(
            "email_outbox.send_failed",
            outbox_id=outbox.id,
            attempts=outbox.attempts,
            error=error,
        )
        outbox.last_error = error
        if outbox.attempts >= MAX_ATTEMPTS:
            outbox.status = "dead"
            session.add(
                EmailLog(
                    entity_type=outbox.entity_type,
                    entity_id=outbox.entity_id,
                    to_addr=outbox.to_addr,
                    subject=f"[dead] {outbox.template}",
                    template=outbox.template,
                    status=EmailStatus.FAILED.value,
                    error=error,
                )
            )
        else:
            outbox.status = "pending"
            outbox.next_attempt_at = _utcnow_naive() + _backoff_delta(
                outbox.attempts
            )
        return

    outbox.status = "sent"
    outbox.last_error = None
    session.add(
        EmailLog(
            entity_type=outbox.entity_type,
            entity_id=outbox.entity_id,
            to_addr=outbox.to_addr,
            subject=subject,
            template=outbox.template,
            status=EmailStatus.SENT.value,
        )
    )


# ----- account hard-delete -----


async def account_hard_delete_handler(
    session: AsyncSession,
    job: ScheduledJob,
    payload: dict[str, Any],
) -> None:
    """Permanently remove every user whose grace window has elapsed.

    Soft-deleted users are anonymised the moment they request deletion;
    this handler completes the GDPR pipeline by deleting the row
    outright once ``scheduled_hard_delete_at`` passes. Cascades fan out
    via the FK definitions in 0001 (auth_sessions, notifications, etc.
    are CASCADE; audit_log.actor_user_id is SET NULL so history is
    preserved with an anonymous actor).
    """
    del job, payload  # tick-driven, scans the whole table

    now = _utcnow_naive()
    targets = list(
        (
            await session.execute(
                select(User).where(
                    User.scheduled_hard_delete_at.is_not(None),
                    User.scheduled_hard_delete_at <= now,
                )
            )
        )
        .scalars()
        .all()
    )
    for user in targets:
        await session.delete(user)
    if targets:
        log.info("account.hard_deleted", count=len(targets))


# ----- registration -----


def register_builtin_handlers() -> None:
    """Register every platform-owned handler with the runner.

    Idempotent — safe to call from worker startup, FastAPI startup, or
    test fixtures (``register_handler`` is last-write-wins on the
    handler dict).
    """
    register_handler("audit_prune", audit_prune_handler)
    register_handler("email_send", email_send_handler)
    register_handler("account_hard_delete", account_hard_delete_handler)
