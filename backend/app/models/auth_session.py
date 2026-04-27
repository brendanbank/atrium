# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Server-side session rows for DB-backed JWT auth.

fastapi-users' default ``JWTStrategy`` is stateless — a stolen cookie
stays valid until the JWT expires, and ``POST /auth/jwt/logout`` is a
no-op server-side. We swap the strategy for ``DBSessionJWTStrategy``
(see ``app.auth.backend``) which creates an ``AuthSession`` row on
login, embeds its id as the ``sid`` claim in the JWT, and rejects any
request whose session row is missing / revoked / expired.

That makes:
- real logout (cookie + row flipped revoked),
- logout-everywhere (every row for a user flipped revoked),
- remote session visibility,
all straightforward.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Opaque session id (UUID4). Embedded in the JWT as the ``sid``
    # claim; the JWT's ``sub`` still carries the user id so legacy
    # code that only reads ``sub`` keeps working.
    session_id: Mapped[str] = mapped_column(
        String(36), nullable=False, unique=True, index=True
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    issued_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Null = active. Set by /auth/jwt/logout (single session),
    # /auth/logout-all (all sessions for the user), and by an admin
    # revoke action in the future.
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )

    # Captured at issue-time for the "active sessions" UI. Truncated
    # to 200 chars — UAs can be long, and we never parse them.
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)

    # Two-phase login flag. For users with a confirmed TOTP, a freshly
    # issued session starts with ``totp_passed=False`` — protected
    # routes reject it until ``/auth/totp/verify`` flips this to True.
    # Users without a confirmed TOTP skip the flag (the app forces
    # them through setup before any other action).
    totp_passed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
