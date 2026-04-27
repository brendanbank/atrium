# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Email outbox queue.

Revision ID: 0002_email_outbox
Revises: 0001_atrium_init
Create Date: 2026-04-26

Adds the ``email_outbox`` table backing the durable retry queue for
outbound mail. ``send_and_log`` stays for synchronous flows; the
outbox is the path for callers that can't lose the message when the
SMTP relay is unreachable.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002_email_outbox"
down_revision = "0001_atrium_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_outbox",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("template", sa.String(100), nullable=False),
        sa.Column("to_addr", sa.String(255), nullable=False),
        sa.Column("context", sa.JSON, nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=True),
        sa.Column("entity_id", sa.BigInteger, nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "attempts", sa.Integer, nullable=False, server_default="0"
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_email_outbox_next_attempt_at",
        "email_outbox",
        ["next_attempt_at"],
    )
    op.create_index(
        "ix_email_outbox_status_next_attempt_at",
        "email_outbox",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_email_outbox_status_next_attempt_at", table_name="email_outbox"
    )
    op.drop_index("ix_email_outbox_next_attempt_at", table_name="email_outbox")
    op.drop_table("email_outbox")
