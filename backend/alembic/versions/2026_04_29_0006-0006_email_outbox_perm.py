# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Seed the ``email_outbox.manage`` permission.

Revision ID: 0006_email_outbox_perm
Revises: 0005_email_template_per_locale
Create Date: 2026-04-29

Atrium 0.16 ships an admin Email outbox tab + ``POST /admin/email-outbox/
{id}/drain`` endpoint. This migration seeds the ``email_outbox.manage``
permission and grants it to ``super_admin`` and ``admin`` (mirroring
the seed in 0001 — ``admin`` gets every permission except
``user.impersonate``).

Idempotent: ``INSERT IGNORE`` so re-running on a partially upgraded DB
is safe. Downgrade revokes the role grants and removes the permission.
"""
from __future__ import annotations

from alembic import op

revision = "0006_email_outbox_perm"
down_revision = "0005_email_template_per_locale"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT IGNORE INTO permissions (code, description)
        VALUES (
            'email_outbox.manage',
            'View the email outbox and drain queued rows on demand.'
        )
        """
    )
    op.execute(
        """
        INSERT IGNORE INTO role_permissions (role_id, permission_code)
        SELECT r.id, 'email_outbox.manage' FROM roles r
        WHERE r.code IN ('super_admin', 'admin')
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions WHERE permission_code = 'email_outbox.manage'"
    )
    op.execute("DELETE FROM permissions WHERE code = 'email_outbox.manage'")
