# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""hello_state table + permission seed

Revision ID: 0001_hello_state
Revises:
Create Date: 2026-04-26
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.auth.rbac_seed import seed_permissions_sync
from sqlalchemy.dialects.mysql import DATETIME as MysqlDATETIME

revision: str = "0001_hello_state"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hello_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column(
            "message",
            sa.String(length=255),
            nullable=False,
            server_default=sa.text("'Hello World!'"),
        ),
        sa.Column(
            "counter",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "updated_at",
            MysqlDATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            server_onupdate=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
    )

    # Singleton row — the router refuses to lazily create one so
    # callers always see the seed defaults.
    op.execute(
        "INSERT INTO hello_state (id, message, counter, enabled) "
        "VALUES (1, 'Hello World!', 0, 0)"
    )

    # Permissions live with the schema (atrium follows the same pattern
    # in 0001_atrium_init). The runtime helper exists for hosts that
    # register permissions dynamically; this example uses the migration
    # form because it's the natural fit for static permissions.
    seed_permissions_sync(
        op.get_bind(),
        ["hello.toggle"],
        grants={"admin": ["hello.toggle"]},
    )


def downgrade() -> None:
    # Permissions intentionally left in place on downgrade — they're
    # cheap to keep and removing them would orphan any UI that still
    # references the code. Operators who really want them gone can
    # `DELETE FROM permissions WHERE code='hello.toggle'` manually.
    op.drop_table("hello_state")
