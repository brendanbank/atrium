# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""End-to-end tests for the host SDK FK helper against a real MySQL.

The unit tests cover marker placement and the alembic op-tree
walker. This file pairs the helper with the actual hello-world host
chain, runs ``alembic upgrade head`` and ``alembic revision
--autogenerate`` against testcontainers MySQL, and checks the
resulting FK behaviour through ``INFORMATION_SCHEMA`` and live
INSERT/DELETE attempts.

Re-uses the session-scoped ``mysql_url`` fixture from
``tests/conftest.py`` (which is what every other integration test
does — running atrium's chain on the same MySQL container atrium
already booted for the rest of the suite). The host's chain shares
the database; its rows live under ``alembic_version_app``, so the
two version tables don't collide.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, text

from alembic import command

# tests/integration/test_host_sdk_alembic.py → repo root → example backend.
HW_BACKEND = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "examples"
    / "hello-world"
    / "backend"
)


def _ensure_hw_on_path() -> None:
    src = str(HW_BACKEND / "src")
    if src not in sys.path:
        sys.path.insert(0, src)


def _hw_alembic_config(async_url: str) -> AlembicConfig:
    cfg = AlembicConfig(str(HW_BACKEND / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", async_url)
    return cfg


def _sync_engine(async_url: str):
    sync_url = async_url.replace("mysql+aiomysql://", "mysql+pymysql://", 1)
    return create_engine(sync_url, pool_pre_ping=True, future=True)


@pytest.fixture
def hw_chain(mysql_url: str):
    """Bring the host's alembic chain up to head, and tear it down.

    Atrium's chain is already at head (the session-scope
    ``run_migrations`` autouse fixture handles that). The host chain
    is independent, so we drive it explicitly here.
    """
    _ensure_hw_on_path()
    cfg = _hw_alembic_config(mysql_url)
    command.upgrade(cfg, "head")
    yield cfg
    command.downgrade(cfg, "base")
    # Drop the version table so the next test starts clean.
    eng = _sync_engine(mysql_url)
    try:
        with eng.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS alembic_version_app"))
    finally:
        eng.dispose()


def test_upgrade_head_creates_fk_in_information_schema(
    mysql_url: str, hw_chain: AlembicConfig
):
    """``alembic upgrade head`` materialises the FK declared via the
    helper into a real database constraint."""
    eng = _sync_engine(mysql_url)
    try:
        with eng.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
                    FROM information_schema.KEY_COLUMN_USAGE
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = 'hello_messages'
                      AND COLUMN_NAME = 'created_by_user_id'
                      AND REFERENCED_TABLE_NAME IS NOT NULL
                    """
                )
            ).one_or_none()
            assert row is not None, "FK on hello_messages.created_by_user_id missing"
            assert row[0] == "users"
            assert row[1] == "id"

            ondelete = conn.execute(
                text(
                    """
                    SELECT DELETE_RULE
                    FROM information_schema.REFERENTIAL_CONSTRAINTS
                    WHERE CONSTRAINT_SCHEMA = DATABASE()
                      AND TABLE_NAME = 'hello_messages'
                    """
                )
            ).scalar_one()
            assert ondelete == "RESTRICT"
    finally:
        eng.dispose()


def test_fk_rejects_orphan_insert(mysql_url: str, hw_chain: AlembicConfig):
    """The DB enforces the FK: inserting a row referencing a
    non-existent ``users.id`` raises a foreign-key error."""
    from sqlalchemy.exc import IntegrityError

    eng = _sync_engine(mysql_url)
    try:
        with eng.begin() as conn, pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO hello_messages (body, created_by_user_id) "
                    "VALUES ('hi', 9999999)"
                )
            )
    finally:
        eng.dispose()


def test_restrict_blocks_user_delete(mysql_url: str, hw_chain: AlembicConfig):
    """``ondelete='RESTRICT'`` propagated through the helper means
    deleting a user that's referenced by a hello_messages row fails."""
    from sqlalchemy.exc import IntegrityError

    eng = _sync_engine(mysql_url)
    try:
        with eng.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (email, hashed_password, full_name, "
                    "is_active, is_verified, preferred_language) "
                    "VALUES ('hostfk@example.com', 'x', 'Host FK', 1, 1, 'en')"
                )
            )
            uid = conn.execute(
                text(
                    "SELECT id FROM users WHERE email='hostfk@example.com'"
                )
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO hello_messages (body, created_by_user_id) "
                    "VALUES ('first', :uid)"
                ),
                {"uid": uid},
            )

        with eng.begin() as conn, pytest.raises(IntegrityError):
            conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})

        # Cleanup: drop the message, then the user — the test fixture
        # only owns the host chain, atrium's tables persist across
        # the session.
        with eng.begin() as conn:
            conn.execute(
                text("DELETE FROM hello_messages WHERE created_by_user_id = :uid"),
                {"uid": uid},
            )
            conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})
    finally:
        eng.dispose()


def test_autogenerate_emits_fk_constraint(mysql_url: str, tmp_path):
    """Run ``alembic revision --autogenerate`` against a chain where
    ``HelloMessage`` is in the host model but NOT in the chain yet.
    The hook must inject the ``ForeignKeyConstraint`` into the
    generated migration body — proving the marker → op-tree transform
    is wired into the host's env.py end-to-end.

    Atrium's tables already exist (the session fixture ran atrium's
    chain). The host alembic chain we use here only has 0001
    applied; the model has ``hello_messages``, so autogenerate sees a
    new table and emits ``create_table`` — the hook is what carries
    the ``ForeignKeyConstraint`` through.
    """
    import shutil

    _ensure_hw_on_path()

    # Clone the host's alembic dir, dropping 0002 so the chain head
    # is 0001 and the model is "ahead" of the chain.
    alembic_dir = tmp_path / "alembic"
    shutil.copytree(HW_BACKEND / "alembic", alembic_dir)
    (alembic_dir / "versions" / "0002_hello_messages.py").unlink(missing_ok=True)

    # Bring the host chain to its trimmed head (0001 only).
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(alembic_dir))
    cfg.set_main_option("sqlalchemy.url", mysql_url)
    command.upgrade(cfg, "head")
    try:
        rev = command.revision(
            cfg,
            message="autogen probe",
            autogenerate=True,
            rev_id="0099_probe",
        )
        out_path = Path(rev.path)
        body = out_path.read_text()
        assert "create_table('hello_messages'" in body, body
        assert "ForeignKeyConstraint" in body, body
        assert "['users.id']" in body, body
        assert "ondelete='RESTRICT'" in body, body
    finally:
        # Tear down: drop hello_state + the host's version table.
        command.downgrade(cfg, "base")
        eng = _sync_engine(mysql_url)
        try:
            with eng.begin() as conn:
                conn.execute(text("DROP TABLE IF EXISTS alembic_version_app"))
        finally:
            eng.dispose()
