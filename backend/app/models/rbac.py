# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""RBAC tables: roles, permissions, and their junctions.

Shape:
    permissions (code PK)
    roles (id PK, code UNIQUE)
    role_permissions (role_id, permission_code)  — many-to-many
    user_roles (user_id, role_id)                — many-to-many

A user's effective permission set is the union over every role they
hold. See ``app.auth.rbac.get_user_permissions`` for the resolver.

Kept separate from ``users.role`` (an enum kept for backward compat) —
that column is a denormalised cache of the primary role and will be
dropped once every call site migrates to ``require_perm``.
"""
from __future__ import annotations

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import TimestampMixin

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column(
        "role_id",
        Integer,
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "permission_code",
        String(100),
        ForeignKey("permissions.code", ondelete="CASCADE"),
        primary_key=True,
    ),
)

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column(
        "user_id",
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "role_id",
        Integer,
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Permission(Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(100), primary_key=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    permissions = relationship(
        Permission, secondary=role_permissions, lazy="selectin"
    )
