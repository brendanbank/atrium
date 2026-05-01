# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Add ``auth_tokens`` table for Personal Access Tokens, plus
``audit_log.token_id`` so per-token audit trails are a single
indexed query.

Revision ID: 0008_add_auth_tokens
Revises: 0007_password_reset_fallback_url
Create Date: 2026-05-01

PATs are opaque bearer tokens with a 12-char public prefix
(``atr_pat_`` + 4 random chars) and an argon2id hash of the full
token. The prefix gives O(1) lookup; the hash defeats brute force
even if the DB is read. ``revoked_at`` immediately invalidates the
token without a row delete (so audit history keeps resolving).

``audit_log.token_id`` is a nullable FK back to ``auth_tokens(id)``
with ``ON DELETE SET NULL`` so revoked-and-purged tokens don't
cascade-delete the audit history they generated.

See atrium issue #112 for the full spec.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008_add_auth_tokens"
down_revision = "0007_password_reset_fallback_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        # Public lookup prefix: ``atr_pat_`` + 4 random base64url chars.
        # Stored unhashed for indexed lookup; the entropy lives in the
        # 32 chars after the prefix (192 bits) and the argon2 hash.
        sa.Column("token_prefix", sa.String(12), nullable=False),
        # argon2id encoded form. Typical length ~96 chars; 255 leaves
        # headroom if the parameters are bumped.
        sa.Column("token_hash", sa.String(255), nullable=False),
        # Permission slugs the issuing user delegated to this token.
        # Intersected with the user's *current* permissions on every
        # request — the JSON list is a stored cap, not a freeze.
        sa.Column("scopes", sa.JSON, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=True),
        sa.Column("last_used_at", sa.DateTime, nullable=True),
        # IPv6 max representation = 39 chars; 45 covers IPv4-mapped
        # IPv6 (``::ffff:192.0.2.0``) too.
        sa.Column("last_used_ip", sa.String(45), nullable=True),
        sa.Column("last_used_user_agent", sa.String(255), nullable=True),
        sa.Column(
            "use_count", sa.Integer, nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("revoked_at", sa.DateTime, nullable=True),
        sa.Column(
            "revoked_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("revoke_reason", sa.String(255), nullable=True),
    )
    # Hot path: the auth middleware filters to (user_id, NOT revoked).
    # Composite index covers it; standalone prefix index covers the
    # request-time lookup.
    op.create_index(
        "ix_auth_tokens_user_active",
        "auth_tokens",
        ["user_id", "revoked_at"],
    )
    op.create_index(
        "ix_auth_tokens_prefix", "auth_tokens", ["token_prefix"]
    )

    # ---- audit_log.token_id ---------------------------------------------
    # Per-token audit views (``GET /admin/auth/tokens/{id}/audit``) want
    # to filter without JSON spelunking. SET NULL on delete so audit
    # history outlives the token row.
    op.add_column(
        "audit_log",
        sa.Column("token_id", sa.Integer, nullable=True),
    )
    op.create_foreign_key(
        "fk_audit_log_token_id",
        source_table="audit_log",
        referent_table="auth_tokens",
        local_cols=["token_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_audit_log_token_id", "audit_log", ["token_id"])


def downgrade() -> None:
    # FK constraint must drop before its index — MySQL rejects with
    # errno 1553 ("needed in a foreign key constraint") otherwise.
    op.drop_constraint("fk_audit_log_token_id", "audit_log", type_="foreignkey")
    op.drop_index("ix_audit_log_token_id", "audit_log")
    op.drop_column("audit_log", "token_id")

    # ``drop_table`` cascade-drops the table's indexes; doing them
    # manually first would 1553 on ``ix_auth_tokens_user_active``
    # because MySQL also uses its leftmost column as the index for
    # the ``user_id`` FK to ``users.id``.
    op.drop_table("auth_tokens")
