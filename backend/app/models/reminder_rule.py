# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.email_template import EmailTemplate
from app.models.mixins import TimestampMixin


class ReminderRule(Base, TimestampMixin):
    """Rule that schedules a reminder email relative to some anchor.

    Atrium ships the table + admin CRUD; host apps decide what
    ``anchor`` and ``kind`` strings mean and provide the logic that
    turns rules into ``ScheduledJob`` rows. ``anchor`` is a free-form
    label (e.g. "user_signup", "booking_arrival"); ``kind`` is the
    semantic class the host's runner uses to short-circuit firing
    (e.g. "skip if already paid"). ``days_offset`` is signed — a
    negative value means "before the anchor".
    """
    __tablename__ = "reminder_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    template_key: Mapped[str] = mapped_column(
        ForeignKey("email_templates.key", ondelete="RESTRICT"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    anchor: Mapped[str] = mapped_column(String(50), nullable=False)
    days_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    template = relationship(EmailTemplate)
