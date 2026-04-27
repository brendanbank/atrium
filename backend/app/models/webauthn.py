# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""WebAuthn / FIDO2 tables.

``WebAuthnCredential`` — one row per registered authenticator. A user
can hold multiple. ``credential_id`` is globally unique.

``WebAuthnChallenge`` — bridges ``begin`` and ``finish`` of each
ceremony. Scoped by ``purpose`` so a registration challenge can't
complete an authentication.
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class WebAuthnCredential(Base):
    __tablename__ = "user_webauthn_credentials"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    credential_id: Mapped[str] = mapped_column(
        String(512), nullable=False, unique=True, index=True
    )
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    transports: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class WebAuthnChallenge(Base):
    __tablename__ = "webauthn_challenges"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    challenge: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
