# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Singleton state row for the Hello World demo.

The host owns its own ``DeclarativeBase`` (and therefore its own
``MetaData``) so atrium's alembic chain never sees this table. The
host's alembic chain manages it under a separate version table
(``alembic_version_app``); see ``alembic/env.py``.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Integer, String, text
from sqlalchemy.dialects.mysql import DATETIME as MysqlDATETIME
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.host_sdk.db import HostForeignKey


class HostBase(DeclarativeBase):
    """Host metadata, separate from atrium's ``app.db.Base``."""


class HelloState(HostBase):
    """Singleton row (id=1) holding the demo's mutable state."""

    __tablename__ = "hello_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    message: Mapped[str] = mapped_column(
        String(255), nullable=False, default="Hello World!"
    )
    counter: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # MySQL DATETIME(6) needed for sub-second precision so concurrent
    # toggles + ticks have a stable updated_at ordering.
    updated_at: Mapped[datetime] = mapped_column(
        MysqlDATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        server_onupdate=text("CURRENT_TIMESTAMP(6)"),
    )


class HelloMessage(HostBase):
    """Append-only log of messages, attributed to the user that wrote them.

    Demonstrates ``HostForeignKey`` for cross-base foreign keys. The
    column references ``users.id`` (an atrium table on a different
    metadata) — a plain ``ForeignKey`` would fail at mapper-init.
    """

    __tablename__ = "hello_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    body: Mapped[str] = mapped_column(String(500), nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(
        Integer,
        HostForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        MysqlDATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
