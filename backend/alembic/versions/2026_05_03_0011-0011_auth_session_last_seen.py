# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Add ``auth_sessions.last_seen_at`` for idle-session timeout enforcement.

Revision ID: 0011_auth_session_last_seen
Revises: 0010_service_accounts_perm
Create Date: 2026-05-03

The DB-backed JWT strategy already rejects rows whose ``expires_at``
has elapsed; idle-timeout adds a second clock that ticks per request.
Existing rows backfill to ``issued_at`` so a long-lived session that
predates the migration is treated as last-seen at issue (matches how
the strategy behaves on the very first request after a fresh login).

The column defaults at the SQL layer to ``CURRENT_TIMESTAMP`` for
new INSERTs that don't supply a value (defence in depth — the
strategy always sets it explicitly).
"""
from __future__ import annotations

from alembic import op

revision = "0011_auth_session_last_seen"
down_revision = "0010_service_accounts_perm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE auth_sessions "
        "ADD COLUMN last_seen_at DATETIME NOT NULL "
        "DEFAULT CURRENT_TIMESTAMP"
    )
    op.execute(
        "UPDATE auth_sessions SET last_seen_at = issued_at "
        "WHERE last_seen_at IS NULL OR last_seen_at < issued_at"
    )
    op.execute(
        "CREATE INDEX ix_auth_sessions_last_seen_at "
        "ON auth_sessions (last_seen_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_auth_sessions_last_seen_at ON auth_sessions")
    op.execute("ALTER TABLE auth_sessions DROP COLUMN last_seen_at")
