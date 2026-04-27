# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Render a DB-stored email template, send it via the configured
backend, and write an email_log row.

Templates live in ``email_templates`` keyed on ``(key, locale)``. The
sender resolves the variant for the recipient's ``preferred_language``
and falls back to ``locale='en'`` when no row exists for the requested
locale — a host app that hasn't authored a translation still ships a
working email instead of a 500.

Subject is a single Jinja line; body is HTML produced by CKEditor with
Jinja expressions inside. A plain-text version of the body is derived
by stripping tags so clients that disable HTML still render sensibly.
"""
from __future__ import annotations

import re
from html import unescape
from typing import Any

from jinja2 import BaseLoader, Environment, StrictUndefined
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.email.backend import EmailMessage, get_mail_backend
from app.logging import log
from app.models.email_outbox import EmailOutbox
from app.models.email_template import EmailTemplate
from app.models.enums import EmailStatus
from app.models.ops import EmailLog

# autoescape is on for every variable, so a guest name like
# ``<script>alert(1)</script>`` or an attacker-controlled notes field
# gets HTML-escaped into the rendered email body rather than executing
# in an owner's inbox. Template authors who genuinely want raw HTML
# (e.g. a precomposed CKEditor body passed through a context var) can
# opt out explicitly with ``{{ value | safe }}``.
_env = Environment(
    loader=BaseLoader(),
    autoescape=True,
    undefined=StrictUndefined,
    keep_trailing_newline=False,
)

_BREAK_RE = re.compile(r"<(br|/p|/li|/h\d|/div)\b[^>]*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")
_BLANK_RE = re.compile(r"\n\s*\n+")

_FALLBACK_LOCALE = "en"


def _html_to_text(html: str) -> str:
    """Coarse HTML to text for the plain-text alternative."""
    text = _BREAK_RE.sub("\n", html)
    text = _TAG_RE.sub("", text)
    text = unescape(text)
    text = _WS_RE.sub(" ", text)
    text = _BLANK_RE.sub("\n\n", text)
    return text.strip() + "\n"


async def _load_template(
    session: AsyncSession, key: str, locale: str = _FALLBACK_LOCALE
) -> EmailTemplate:
    """Resolve the (key, locale) row, falling back to (key, 'en').

    Raises ``LookupError`` when neither the requested locale nor the
    English fallback exists — the caller's error path turns that into a
    failed ``email_log`` row plus a structlog ERROR line so a missing
    template surfaces in /admin mail log rather than a silent stuck
    queue.
    """
    row = (
        await session.execute(
            select(EmailTemplate).where(
                EmailTemplate.key == key,
                EmailTemplate.locale == locale,
            )
        )
    ).scalar_one_or_none()
    if row is None and locale != _FALLBACK_LOCALE:
        row = (
            await session.execute(
                select(EmailTemplate).where(
                    EmailTemplate.key == key,
                    EmailTemplate.locale == _FALLBACK_LOCALE,
                )
            )
        ).scalar_one_or_none()
    if row is None:
        raise LookupError(
            f"email template '{key}' not found "
            "(checked locale and 'en' fallback) - "
            "add it via Admin / Email templates"
        )
    return row


async def render_template(
    session: AsyncSession,
    key: str,
    context: dict[str, Any],
    locale: str = _FALLBACK_LOCALE,
) -> tuple[str, str, str]:
    """Return (subject, text_body, html_body) rendered from the DB row.

    ``locale`` selects which (key, locale) row to load; missing locales
    fall back to English (see ``_load_template``).
    """
    row = await _load_template(session, key, locale)
    subject = _env.from_string(row.subject).render(**context).strip()
    body_html = _env.from_string(row.body_html).render(**context)
    body_text = _html_to_text(body_html)
    return subject, body_text, body_html


async def send_and_log(
    session: AsyncSession,
    *,
    template: str,
    to: list[str],
    context: dict[str, Any],
    entity_type: str | None = None,
    entity_id: int | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    reply_to: str | None = None,
    locale: str = _FALLBACK_LOCALE,
) -> None:
    """Render ``template`` for ``locale``, send it, write email_log rows.

    Pass the recipient's ``preferred_language`` (or the inviter's, in
    invite flows where the recipient has no preference yet) as
    ``locale``. Missing translations fall back to English silently.
    """
    # Render failures (bad Jinja, undefined variable, template row
    # missing) are separate from SMTP failures: the SMTP relay is
    # "flaky infra, retry and forget", a render failure is a bug that
    # nobody will see until somebody greps structlog. Record a failed
    # EmailLog row so the /admin mail log makes the break visible, and
    # log at ERROR so alerting picks it up.
    try:
        subject, text, html = await render_template(
            session, template, context, locale
        )
    except Exception as exc:
        error = f"{exc.__class__.__name__}: {exc}"
        log.error(
            "email.render_failed",
            template=template,
            locale=locale,
            to=to,
            error=error,
        )
        for addr in to:
            session.add(
                EmailLog(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    to_addr=addr,
                    subject=f"[render failed] {template}",
                    template=template,
                    status=EmailStatus.FAILED.value,
                    error=error,
                )
            )
        await session.flush()
        raise RuntimeError(error) from exc

    backend = get_mail_backend()
    message = EmailMessage(
        to=to,
        subject=subject,
        body_text=text,
        body_html=html,
        cc=cc or [],
        bcc=bcc or [],
        reply_to=reply_to,
        template=template,
    )

    error: str | None = None
    try:
        await backend.send(message)
        status = EmailStatus.SENT.value
    except Exception as exc:
        status = EmailStatus.FAILED.value
        error = f"{exc.__class__.__name__}: {exc}"
        log.error(
            "email.send_failed",
            template=template,
            locale=locale,
            to=to,
            error=error,
        )

    for addr in to:
        session.add(
            EmailLog(
                entity_type=entity_type,
                entity_id=entity_id,
                to_addr=addr,
                subject=subject,
                template=template,
                status=status,
                error=error,
            )
        )
    await session.flush()
    if error is not None:
        raise RuntimeError(error)


async def enqueue_and_log(
    session: AsyncSession,
    *,
    template: str,
    to: list[str],
    context: dict[str, Any],
    entity_type: str | None = None,
    entity_id: int | None = None,
    locale: str = _FALLBACK_LOCALE,
) -> list[EmailOutbox]:
    """Queue an email for durable, retried delivery.

    Inserts one ``email_outbox`` row per recipient (status=``pending``,
    next_attempt_at=now) plus a corresponding ``email_log`` row with
    ``status=queued``. The worker drains pending rows via the
    ``email_send`` job handler (exponential backoff, dead-letter on
    repeated failure) - this function does NOT send.

    The ``locale`` is persisted on the outbox row so the worker
    re-renders against the same variant on retry, even if the
    recipient's ``preferred_language`` changes between enqueue and
    drain.

    The template existence is validated up-front (in the requested
    locale or its EN fallback) so a typo or missing row fails the
    caller's request synchronously instead of leaving a stuck row that
    only fails when drained. Caller controls the transaction; nothing
    is committed here.
    """
    await _load_template(session, template, locale)

    rows: list[EmailOutbox] = []
    for addr in to:
        outbox = EmailOutbox(
            template=template,
            to_addr=addr,
            context=context,
            entity_type=entity_type,
            entity_id=entity_id,
            status="pending",
            attempts=0,
            next_attempt_at=func.now(),
            locale=locale,
        )
        session.add(outbox)
        rows.append(outbox)
        session.add(
            EmailLog(
                entity_type=entity_type,
                entity_id=entity_id,
                to_addr=addr,
                # Subject isn't rendered yet; record the template key so
                # the admin mail log can still attribute the row.
                subject=f"[queued] {template}",
                template=template,
                status=EmailStatus.QUEUED.value,
            )
        )
    await session.flush()
    return rows
