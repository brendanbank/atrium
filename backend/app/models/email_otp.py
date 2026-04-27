# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Email-OTP second-factor tables.

``UserEmailOTP`` mirrors ``UserTOTP``: one row per user who has opted
into email-delivered codes, with ``confirmed_at`` gating the login
flow. Users can hold both rows at once — the challenge screen lets
them pick.

``EmailOTPChallenge`` is the short-lived per-login code. The raw
6-digit code is never stored; ``code_hash`` is its sha256.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserEmailOTP(Base):
    __tablename__ = "user_email_otp"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class EmailOTPChallenge(Base):
    __tablename__ = "email_otp_challenges"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, index=True
    )
    # Null = still redeemable. Set on verify to prevent replay within
    # the 10-minute window.
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
