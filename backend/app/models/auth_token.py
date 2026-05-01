# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Personal Access Token model.

PATs are opaque bearer tokens scoped to a subset of the issuing
user's permissions. The plaintext token is shown to the operator
exactly once at creation and never persisted; only the
``token_prefix`` (12 chars, public) and ``token_hash`` (argon2id,
~96 chars) live in the DB.

The prefix is used for indexed lookup at request time; the hash
is verified once per request. Effective scopes for a given request
are the intersection of the row's ``scopes`` with the user's
*current* permissions, computed at auth time — a token cannot do
what its user cannot. See atrium issue #112 for the full design.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.auth import User


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Who issued the token. Usually the same as ``user_id`` (self-issue),
    # but a super-admin creating a service-account PAT sets this to
    # their own id. Nullable + SET NULL on delete so the audit trail
    # survives the issuer being removed.
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # ``atr_pat_`` + first 4 chars of the random secret. Public; used
    # for indexed lookup. The full token's entropy lives in the 32
    # chars after the prefix.
    token_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    # argon2id encoded form. Verification is intentionally slow to
    # defeat brute force; the prefix index ensures we verify exactly
    # one (or rarely a tiny handful of) candidate per request.
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Permission slugs this token is willing to delegate. Intersected
    # with the user's current permission set on every request — the
    # stored list is a cap, not a freeze.
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    last_used_user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False
    )

    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    revoke_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    created_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[created_by_user_id]
    )
    revoked_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[revoked_by_user_id]
    )

    def to_summary(self) -> dict[str, Any]:
        """Serialise for the list / show endpoints (plaintext NEVER
        included). The middleware and creation endpoint hand back
        the plaintext separately."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "token_prefix": self.token_prefix,
            "scopes": list(self.scopes or []),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "last_used_at": (
                self.last_used_at.isoformat() if self.last_used_at else None
            ),
            "last_used_ip": self.last_used_ip,
            "use_count": self.use_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "revoke_reason": self.revoke_reason,
        }
