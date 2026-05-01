# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Add ``users.is_service_account`` and seed PAT permissions.

Revision ID: 0009_users_service_account
Revises: 0008_add_auth_tokens
Create Date: 2026-05-01

Service accounts are users that hold PATs but never log in
interactively. They exist so long-lived non-human consumers (the
atrium-pa MCP sidecar, backup scripts, future per-agent identities)
can have their own audit identity instead of riding on a human user.

Pre-implementation spike (issue #112): fastapi-users 13.x's
``PasswordHelper.verify_and_update`` calls into ``bcrypt`` /
``pwdlib`` which expects a string and would crash (or silently
return False after AttributeError) on ``None``. Rather than risk
upstream surprise, service accounts use ``hashed_password = ""``
as a sentinel — same convention as the soft-delete flow. The
empty string can never bcrypt-match any input, and the
``is_service_account`` flag does the actual gating. Result: no
nullable change to ``hashed_password``; only the boolean column
is new.

Permission seeds:
- ``auth.pats.read_self`` — granted to every system role so any user
  can list their own tokens. First permission held by the ``user``
  role (which has none today), so add to all three.
- ``auth.pats.admin_read`` — super_admin only. Visible per spec §10.
- ``auth.pats.admin_revoke`` — super_admin only. Mirrors the existing
  ``user.impersonate`` carve-out (admin gets every permission *except*
  these privileged ones).
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009_users_service_account"
down_revision = "0008_add_auth_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_service_account",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_users_is_service_account",
        "users",
        ["is_service_account"],
    )

    # ---- PAT permission seeds ------------------------------------------
    op.execute(
        """
        INSERT IGNORE INTO permissions (code, description) VALUES
            ('auth.pats.read_self', 'List and inspect one''s own personal access tokens.'),
            ('auth.pats.admin_read', 'View every personal access token across all users.'),
            ('auth.pats.admin_revoke', 'Revoke another user''s personal access tokens.')
        """
    )

    # read_self: every system role (user / admin / super_admin).
    op.execute(
        """
        INSERT IGNORE INTO role_permissions (role_id, permission_code)
        SELECT r.id, 'auth.pats.read_self' FROM roles r
        WHERE r.code IN ('super_admin', 'admin', 'user')
        """
    )
    # admin_read + admin_revoke: super_admin only. Mirrors the
    # ``user.impersonate`` precedent — privileged enough that the
    # ``admin`` role does *not* get them by default.
    op.execute(
        """
        INSERT IGNORE INTO role_permissions (role_id, permission_code)
        SELECT r.id, 'auth.pats.admin_read' FROM roles r
        WHERE r.code = 'super_admin'
        """
    )
    op.execute(
        """
        INSERT IGNORE INTO role_permissions (role_id, permission_code)
        SELECT r.id, 'auth.pats.admin_revoke' FROM roles r
        WHERE r.code = 'super_admin'
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions WHERE permission_code IN "
        "('auth.pats.read_self', 'auth.pats.admin_read', 'auth.pats.admin_revoke')"
    )
    op.execute(
        "DELETE FROM permissions WHERE code IN "
        "('auth.pats.read_self', 'auth.pats.admin_read', 'auth.pats.admin_revoke')"
    )
    op.drop_index("ix_users_is_service_account", "users")
    op.drop_column("users", "is_service_account")
