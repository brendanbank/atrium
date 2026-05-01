# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Seed the ``auth.service_accounts.manage`` permission.

Revision ID: 0010_service_accounts_perm
Revises: 0009_users_service_account
Create Date: 2026-05-01

Service-account creation + listing is super-admin-only territory:
issuing a non-human identity that holds long-lived bearer tokens is
operationally sensitive in the same way ``user.impersonate`` is. The
``admin`` role does not get this permission by default, mirroring the
existing privilege carve-out on the impersonation flag (see
0001_atrium_init).
"""
from __future__ import annotations

from alembic import op

revision = "0010_service_accounts_perm"
down_revision = "0009_users_service_account"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT IGNORE INTO permissions (code, description) VALUES
            ('auth.service_accounts.manage',
             'Create and list non-human service-account identities.')
        """
    )
    op.execute(
        """
        INSERT IGNORE INTO role_permissions (role_id, permission_code)
        SELECT r.id, 'auth.service_accounts.manage' FROM roles r
        WHERE r.code = 'super_admin'
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions "
        "WHERE permission_code = 'auth.service_accounts.manage'"
    )
    op.execute(
        "DELETE FROM permissions "
        "WHERE code = 'auth.service_accounts.manage'"
    )
