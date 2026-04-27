# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Pluggable mail backend.

The active backend is chosen by the ``MAIL_BACKEND`` env var:
- ``console`` — prints the message to stdout/logs; never opens a
  network connection. The default in development so no stray emails
  reach real inboxes.
- ``smtp`` — relays via aiosmtplib to ``SMTP_HOST``. The default in
  production (host-side Postfix for this deployment).
- ``dummy`` — silently drops messages; useful for tests that assert
  send attempts without inspecting output.

Selection logic (see ``_resolve_backend_name``):
1. If ``MAIL_BACKEND`` is set, use it.
2. Else if ``ENVIRONMENT=prod``, use ``smtp``.
3. Else use ``console``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from email.message import EmailMessage as StdEmailMessage
from typing import Literal, Protocol

from app.logging import log
from app.settings import get_settings


@dataclass
class EmailMessage:
    to: list[str]
    subject: str
    body_text: str
    body_html: str | None = None
    from_: str | None = None  # falls back to settings.mail_from
    reply_to: str | None = None
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    # Used only for logging / email_log — not wire headers
    template: str = "ad-hoc"


class MailBackend(Protocol):
    name: str

    async def send(self, message: EmailMessage) -> None: ...


# -----------------------------------------------------------------------------
# Implementations
# -----------------------------------------------------------------------------


class ConsoleMailBackend:
    """Development backend — prints the message to stdout.

    Never opens an SMTP connection. Safe to use even without network.
    The raw body is printed verbatim (rather than folded into a single
    structlog key) so it reads like a real email in container logs.
    """
    name = "console"

    async def send(self, message: EmailMessage) -> None:
        settings = get_settings()
        sender = message.from_ or settings.mail_from
        reply_to = message.reply_to or settings.mail_reply_to

        lines = [
            "",
            "=" * 70,
            f"[email/console] template={message.template}",
            f"From:     {sender}",
            f"To:       {', '.join(message.to)}",
        ]
        if message.cc:
            lines.append(f"Cc:       {', '.join(message.cc)}")
        if message.bcc:
            lines.append(f"Bcc:      {', '.join(message.bcc)}")
        if reply_to:
            lines.append(f"Reply-To: {reply_to}")
        lines.append(f"Subject:  {message.subject}")
        lines.append("-" * 70)
        lines.append(message.body_text.rstrip())
        if message.body_html:
            lines.append("-" * 70)
            lines.append(f"[html body present — {len(message.body_html)} chars]")
        lines.append("=" * 70)
        lines.append("")

        # Bypass structlog so the body isn't escaped or folded into kv pairs.
        print("\n".join(lines), flush=True)

        log.info(
            "email.console_send",
            backend="console",
            to=message.to,
            template=message.template,
            subject=message.subject,
        )


class DummyMailBackend:
    """Silently drops messages. For tests that don't want log noise."""
    name = "dummy"

    async def send(self, message: EmailMessage) -> None:
        return None


class SmtpMailBackend:
    """Production backend — relays via aiosmtplib.

    In this deployment ``SMTP_HOST=host.docker.internal`` points at the
    host's Postfix, which handles SPF/DKIM/DMARC. The container only
    needs a working relay.
    """
    name = "smtp"

    async def send(self, message: EmailMessage) -> None:
        import aiosmtplib  # local import: avoid import cost on console path

        settings = get_settings()
        msg = StdEmailMessage()
        msg["From"] = message.from_ or settings.mail_from
        msg["To"] = ", ".join(message.to)
        if message.cc:
            msg["Cc"] = ", ".join(message.cc)
        if message.reply_to or settings.mail_reply_to:
            msg["Reply-To"] = message.reply_to or settings.mail_reply_to
        msg["Subject"] = message.subject
        msg.set_content(message.body_text)
        if message.body_html:
            msg.add_alternative(message.body_html, subtype="html")

        recipients = [*message.to, *message.cc, *message.bcc]

        await aiosmtplib.send(
            msg,
            recipients=recipients,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username or None,
            password=settings.smtp_password or None,
            use_tls=settings.smtp_use_tls,
            start_tls=False,
            timeout=15,
        )
        log.info(
            "email.smtp_send",
            backend="smtp",
            to=message.to,
            subject=message.subject,
            template=message.template,
        )


# -----------------------------------------------------------------------------
# Selection
# -----------------------------------------------------------------------------

BackendName = Literal["console", "smtp", "dummy"]


def _resolve_backend_name() -> BackendName:
    settings = get_settings()
    explicit = (settings.mail_backend or "").strip().lower()
    if explicit in {"console", "smtp", "dummy"}:
        return explicit  # type: ignore[return-value]
    return "smtp" if settings.environment == "prod" else "console"


_cached_backend: MailBackend | None = None


def get_mail_backend() -> MailBackend:
    """Return the configured mail backend (cached per-process)."""
    global _cached_backend
    if _cached_backend is not None:
        return _cached_backend

    name = _resolve_backend_name()
    if name == "smtp":
        _cached_backend = SmtpMailBackend()
    elif name == "dummy":
        _cached_backend = DummyMailBackend()
    else:
        _cached_backend = ConsoleMailBackend()

    log.info("email.backend_selected", backend=_cached_backend.name)
    return _cached_backend


def reset_mail_backend_for_tests() -> None:
    """Tests sometimes need to swap the cache (e.g., after monkey-patching env)."""
    global _cached_backend
    _cached_backend = None
