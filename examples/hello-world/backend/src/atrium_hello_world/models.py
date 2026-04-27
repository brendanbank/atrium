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
