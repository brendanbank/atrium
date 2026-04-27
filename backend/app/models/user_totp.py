# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""TOTP enrollment row per user.

Paired with ``app.services.totp`` for secret generation, provisioning
URIs, and code verification. See migration 0017 for the column
rationale — notably, the raw base32 secret is stored in plaintext
because it's already a server-side secret.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserTOTP(Base):
    __tablename__ = "user_totp"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    secret: Mapped[str] = mapped_column(String(64), nullable=False)
    # Null until the user submits their first valid code. Before that,
    # login is blocked and the UI forces the setup screen.
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    # Last step boundary that successfully authenticated. Used to
    # reject replay within the same 30s window.
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
