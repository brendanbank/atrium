# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Self-serve signup + email verification.

Revision ID: 0004_email_verifications
Revises: 0003_user_soft_delete
Create Date: 2026-04-26

Adds ``users.email_verified_at`` (timestamp the user clicked the
verification link, NULL for unverified accounts), the
``email_verifications`` token table that backs the verify-email flow,
and seeds the ``email_verify`` template the signup service renders.

Tokens are stored as their sha256 digest only (a leaked DB dump can't
be replayed) and have a 24h TTL enforced at consume time.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0004_email_verifications"
down_revision = "0003_user_soft_delete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime, nullable=True),
    )

    op.create_table(
        "email_verifications",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        # ``users.id`` is INT — MySQL refuses the FK if the columns
        # don't match exactly. The volume on this table is bounded
        # (one row per signup until consumed/expired), so INT is
        # plenty even at scale.
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_sha256", sa.CHAR(64), nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("consumed_at", sa.DateTime, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_email_verifications_token_sha256",
        "email_verifications",
        ["token_sha256"],
        unique=True,
    )
    op.create_index(
        "ix_email_verifications_user_id",
        "email_verifications",
        ["user_id"],
    )

    op.bulk_insert(
        sa.table(
            "email_templates",
            sa.column("key", sa.String),
            sa.column("subject", sa.String),
            sa.column("body_html", sa.Text),
            sa.column("description", sa.String),
        ),
        [
            {
                "key": "email_verify",
                "subject": "Verify your email for {{ brand_name }}",
                "body_html": (
                    "<p>Hello {{ recipient.full_name }},</p>"
                    "<p>Welcome to {{ brand_name }}. Please confirm "
                    "this email address so you can sign in.</p>"
                    "<p><a href=\"{{ verify_url }}\">Verify your "
                    "email</a></p>"
                    # Plain-text fallback URL — the console mail
                    # backend strips tags so the anchor's href would
                    # otherwise be invisible to anyone reading the
                    # text version (e.g. plaintext-only mail clients,
                    # the e2e test suite scraping docker logs).
                    "<p style=\"font-size:12px;color:#666\">"
                    "Or paste this link: {{ verify_url }}"
                    "</p>"
                    "<p>The link expires in 24 hours. If you didn't "
                    "create an account, you can ignore this message.</p>"
                ),
                "description": (
                    "Sent after self-serve signup. The user must click "
                    "the link before they can log in when "
                    "auth.require_email_verification is True."
                ),
            },
        ],
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM email_templates WHERE `key` = 'email_verify'"
    )
    op.drop_index(
        "ix_email_verifications_user_id", table_name="email_verifications"
    )
    op.drop_index(
        "ix_email_verifications_token_sha256",
        table_name="email_verifications",
    )
    op.drop_table("email_verifications")
    op.drop_column("users", "email_verified_at")
