# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Add ``user_secret_keys`` — per-user data-encryption keys.

Revision ID: 0012_user_secret_keys
Revises: 0011_auth_session_last_seen
Create Date: 2026-08-15

Atrium's first secret-bearing table, and the reason issue #227 needed
one. ``scope="site"`` keys (0.27.0) are HKDF-derived from
``SECRET_ENCRYPTION_KEY``, which is fine for a secret the whole
installation shares but cannot support shredding: a derived key is
recomputable from the master forever, so "destroy the user's key"
would be a no-op.

A user's key is therefore 32 random bytes, stored wrapped under the
master. ``ON DELETE CASCADE`` is the shredding mechanism — when the
``users`` row goes, the only copy of that key goes with it, and every
ciphertext ever written for that user is unreadable from then on,
including in backups taken before the delete.

Empty on upgrade: rows materialise the first time a host calls
``unlock_user_secrets(..., create=True)``. Downgrade drops the table,
which shreds every user key — that is unavoidable and is why the
docstring says so out loud.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0012_user_secret_keys"
down_revision = "0011_auth_session_last_seen"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_secret_keys",
        # One key per user, so the user id *is* the primary key rather
        # than a surrogate with a unique constraint beside it.
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
            autoincrement=False,
        ),
        # ATR | version | scope | nonce | ct | tag over the 32-byte key.
        # 61 bytes today; 255 leaves room for a future wire revision
        # without a schema change.
        sa.Column("wrapped_key", sa.LargeBinary(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    # Destroys every user key. Any user-scope ciphertext still in the
    # database becomes permanently unreadable — there is no other copy
    # by design.
    op.drop_table("user_secret_keys")
