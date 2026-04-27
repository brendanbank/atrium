# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Outbox queue for outbound email.

When ``MAIL_BACKEND=smtp`` and the relay is unavailable, ``send_and_log``
either loses the message or raises into the request handler. The outbox
queue gives us a durable hand-off: ``enqueue_and_log`` writes a row that
the worker drains via the ``email_send`` job handler with exponential
backoff and a dead-letter terminal state.
"""
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin


class EmailOutbox(Base, TimestampMixin):
    """One row per recipient per send.

    ``status`` transitions: ``pending`` -> ``sending`` -> (``sent`` |
    failed-and-retried-as ``pending`` | exhausted-as ``dead``). The
    composite index on (status, next_attempt_at) supports the worker's
    drain query, which only ever asks for pending rows due now.
    """
    __tablename__ = "email_outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    template: Mapped[str] = mapped_column(String(100), nullable=False)
    to_addr: Mapped[str] = mapped_column(String(255), nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        index=True,
        server_default=func.now(),
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Locale the queued email should render against. Persisted on the
    # row so the worker re-renders the same translation on retry, even
    # if the recipient's preferred_language changes after enqueue.
    locale: Mapped[str] = mapped_column(
        String(10), nullable=False, default="en", server_default="en"
    )

    __table_args__ = (
        Index("ix_email_outbox_status_next_attempt_at", "status", "next_attempt_at"),
    )
