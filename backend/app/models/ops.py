# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Operational tables: notifications, scheduled jobs, email log, audit log,
app settings. These are infrastructure, not core domain."""
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.enums import EmailStatus, JobState
from app.models.mixins import TimestampMixin


class Notification(Base):
    """In-app notification for a user.

    Surfaced via the notification bell. Email notifications are logged
    separately in `email_log`.
    """
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class ScheduledJob(Base, TimestampMixin):
    """Domain-level record of work the worker needs to do.

    APScheduler has its own job store for heartbeat; this table is the
    source of truth for queued work so cancellation and audit are
    possible from the UI. ``entity_type`` + ``entity_id`` let host apps
    attribute a job to a domain row (e.g. ``("booking", 42)``) without
    a hard FK; null when a job isn't tied to any entity.
    """
    __tablename__ = "scheduled_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    entity_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True, index=True
    )
    entity_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True
    )
    job_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    run_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    state: Mapped[JobState] = mapped_column(
        String(20), nullable=False, default=JobState.PENDING.value, index=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class EmailLog(Base):
    """Every outbound email sent by the system."""
    __tablename__ = "email_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    entity_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True, index=True
    )
    entity_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True
    )
    to_addr: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    template: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[EmailStatus] = mapped_column(String(20), nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class AuditLog(Base):
    """Tamper-evident action log for compliance-sensitive changes."""
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Set when a super_admin was impersonating someone during this
    # action — lets the audit distinguish "target did X" from
    # "super_admin did X while impersonating target". Null for normal
    # (non-impersonated) sessions. Populated automatically from the
    # impersonator cookie by the audit middleware; callers don't pass
    # it explicitly.
    impersonator_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    entity: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    diff: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class AppSetting(Base):
    """Key/value app-wide settings tunable from the admin UI."""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
