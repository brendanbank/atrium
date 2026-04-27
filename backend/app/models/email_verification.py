# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Email-verification token table for the self-serve signup flow.

One row per outstanding verification challenge. The raw token is never
stored — only its sha256 digest, so a leaked DB dump can't be replayed
to verify an attacker-controlled inbox.

Rows live until consumed or expired; the cleanup pass is opportunistic
(``consume_verification`` rejects expired/consumed rows on lookup).
"""
from datetime import datetime

from sqlalchemy import CHAR, BigInteger, DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class EmailVerification(Base):
    __tablename__ = "email_verifications"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    # users.id is INT (see migration 0001); the FK enforces the same
    # type. INT is plenty for verification rows.
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_sha256: Mapped[str] = mapped_column(
        CHAR(64), nullable=False, unique=True, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
