# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import Language
from app.models.mixins import TimestampMixin


class User(Base, TimestampMixin):
    """Application user.

    Defines the columns fastapi-users expects (email, hashed_password,
    is_active, is_verified) explicitly. ``is_superuser`` is omitted —
    admin authority flows through the RBAC ``super_admin`` role and
    permission-based gates. fastapi-users only reads ``is_superuser``
    when a dependency is declared with ``superuser=True``, which we
    never do.
    """
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    email: Mapped[str] = mapped_column(
        String(320), unique=True, index=True, nullable=False
    )
    hashed_password: Mapped[str] = mapped_column(String(1024), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    preferred_language: Mapped[Language] = mapped_column(
        String(5), nullable=False, default=Language.EN.value
    )

    # Soft-delete: ``deleted_at`` flips at the moment the user (or an
    # admin) initiates deletion; PII columns are anonymised in the same
    # transaction so the row can no longer authenticate or be matched
    # back to a person. ``scheduled_hard_delete_at`` is when the worker
    # actually removes the row — kept around through the grace window
    # so audit_log foreign keys keep resolving while the deletion is
    # still cancellable.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    scheduled_hard_delete_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True, index=True
    )

    # Set when the self-serve signup flow's verification link is
    # consumed. ``None`` means the email is unverified — under
    # ``auth.require_email_verification`` the login path refuses these.
    # Distinct from ``is_verified`` (which fastapi-users uses for its
    # own verification flow); we keep both so existing invite-created
    # accounts (is_verified=True, email_verified_at=None) still pass.
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )


class UserInvite(Base, TimestampMixin):
    """Invitation to create an account. No public signup."""
    __tablename__ = "user_invites"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    # RBAC role codes (e.g. ["admin", "user"]) granted on accept. Stored
    # as JSON so a single invite can carry any combination of roles.
    role_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)

    invited_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )

    invited_by = relationship("User", foreign_keys=[invited_by_user_id])
