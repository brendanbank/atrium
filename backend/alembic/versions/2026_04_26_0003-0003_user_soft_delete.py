# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""User soft-delete columns + GDPR deletion email templates.

Revision ID: 0003_user_soft_delete
Revises: 0002_email_outbox
Create Date: 2026-04-26

Adds ``deleted_at`` and ``scheduled_hard_delete_at`` to ``users``. The
hard-delete worker scans by the latter on a daily tick, so it gets an
index. The user row stays around through the grace period so audit
log foreign keys keep pointing somewhere meaningful — anonymisation
lives in the application layer (email/full_name/password rewritten on
soft-delete).

Seeds two email templates: one to confirm the self-initiated deletion
to the user, one to notify admins when a super_admin removes someone
else's account.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_user_soft_delete"
down_revision = "0002_email_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("deleted_at", sa.DateTime, nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("scheduled_hard_delete_at", sa.DateTime, nullable=True),
    )
    op.create_index(
        "ix_users_scheduled_hard_delete_at",
        "users",
        ["scheduled_hard_delete_at"],
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
                "key": "account_delete_confirm",
                "subject": "Your account is scheduled for deletion",
                "body_html": (
                    "<p>Hello {{ recipient.full_name }},</p>"
                    "<p>Your account is scheduled for deletion on "
                    "<strong>{{ date }}</strong>.</p>"
                    "<p>Until then, your sign-in is disabled. If this was a "
                    "mistake, reply to this message or contact "
                    "<a href=\"mailto:{{ support_email }}\">{{ support_email }}</a> "
                    "to cancel the deletion.</p>"
                    "<p>After {{ date }} the account and its personal data "
                    "are permanently removed.</p>"
                ),
                "description": (
                    "Sent to a user who has just self-initiated account "
                    "deletion, with the date the hard-delete worker will "
                    "remove the row."
                ),
            },
            {
                "key": "account_delete_admin_notice",
                "subject": "Account deleted by an administrator",
                "body_html": (
                    "<p>Hello {{ recipient.full_name }},</p>"
                    "<p>{{ admin.full_name }} ({{ admin.email }}) has just "
                    "deleted your account. Personal data is being purged on "
                    "{{ date }}.</p>"
                    "<p>If you didn't expect this, contact your "
                    "administrator.</p>"
                ),
                "description": (
                    "Heads-up sent when a super_admin manually deletes "
                    "someone else's account."
                ),
            },
        ],
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM email_templates WHERE `key` IN "
        "('account_delete_confirm', 'account_delete_admin_notice')"
    )
    op.drop_index(
        "ix_users_scheduled_hard_delete_at", table_name="users"
    )
    op.drop_column("users", "scheduled_hard_delete_at")
    op.drop_column("users", "deleted_at")
