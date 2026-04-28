# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""hello_messages table — exercises HostForeignKey end-to-end

Revision ID: 0002_hello_messages
Revises: 0001_hello_state
Create Date: 2026-04-28
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME as MysqlDATETIME

revision: str = "0002_hello_messages"
down_revision: str | None = "0001_hello_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Body of this migration was produced by ``alembic revision
    # --autogenerate`` against the host model in ``models.py``. The
    # ``ForeignKeyConstraint`` against ``users.id`` was emitted
    # automatically by ``app.host_sdk.alembic.emit_host_foreign_keys``
    # — there's no column-level ``ForeignKey()`` on the ORM side, so
    # without that hook autogenerate would skip the constraint and a
    # host integrator would be writing it by hand. See
    # ``docs/host-models.md``.
    op.create_table(
        "hello_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("body", sa.String(length=500), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            MysqlDATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_hello_messages_created_by_user_id"),
        "hello_messages",
        ["created_by_user_id"],
        unique=False,
    )


def downgrade() -> None:
    # MySQL refuses to drop the FK-backing index while the constraint
    # still exists; drop_table cascades both, so we just lean on it.
    op.drop_table("hello_messages")
