# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Idempotent permission + role-grant seeding (rbac_seed module).

Three contracts:

1. Seeding twice is a no-op — the runtime form runs on every host
   ``init_app`` startup, so repeated calls must not double-insert.
2. ``super_admin`` auto-receives every newly seeded permission, mirror
   of the migration-0001 seed pattern (host operators expect
   "super_admin sees everything" without per-permission ceremony).
3. Unknown role codes in ``grants`` are skipped with a log warning,
   not raised — host apps may opt into a smaller role set than atrium
   ships, and a missing role shouldn't crash startup.

Also covered: the sync sibling (``seed_permissions_sync``) walks the
same SQL paths via ``op.get_bind()``-style sync connections used inside
alembic migrations.

The ``permissions`` table is in the conftest truncate-skip list (it's
seeded once by migration and assumed invariant), so each test cleans
up the test-specific permission codes it wrote on teardown.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth.rbac_seed import seed_permissions, seed_permissions_sync
from app.models.rbac import Permission, Role, role_permissions

_TEST_PERM_PREFIX = "test_rbac_seed."


@pytest_asyncio.fixture
async def _cleanup_test_perms(engine):
    """Wipe any permission row whose code begins with the test prefix
    on teardown, plus the role_permissions rows that referenced it."""
    yield
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await s.execute(
            text(
                "DELETE FROM role_permissions "
                "WHERE permission_code LIKE :prefix"
            ),
            {"prefix": f"{_TEST_PERM_PREFIX}%"},
        )
        await s.execute(
            text("DELETE FROM permissions WHERE code LIKE :prefix"),
            {"prefix": f"{_TEST_PERM_PREFIX}%"},
        )
        await s.commit()


@pytest.mark.asyncio
async def test_seed_inserts_permission_once(engine, _cleanup_test_perms):
    code = f"{_TEST_PERM_PREFIX}toggle"
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await seed_permissions(s, [code])
        await s.commit()

    async with factory() as s:
        rows = (
            await s.execute(
                select(Permission.code).where(Permission.code == code)
            )
        ).scalars().all()
    assert rows == [code]


@pytest.mark.asyncio
async def test_seed_is_idempotent(engine, _cleanup_test_perms):
    code = f"{_TEST_PERM_PREFIX}idempotent"
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await seed_permissions(s, [code], grants={"admin": [code]})
        await s.commit()
    async with factory() as s:
        await seed_permissions(s, [code], grants={"admin": [code]})
        await s.commit()

    async with factory() as s:
        perm_count = (
            await s.execute(
                select(Permission).where(Permission.code == code)
            )
        ).scalars().all()
        admin_id = (
            await s.execute(select(Role.id).where(Role.code == "admin"))
        ).scalar_one()
        grant_rows = (
            await s.execute(
                select(role_permissions).where(
                    role_permissions.c.permission_code == code,
                    role_permissions.c.role_id == admin_id,
                )
            )
        ).all()

    assert len(perm_count) == 1
    assert len(grant_rows) == 1


@pytest.mark.asyncio
async def test_super_admin_auto_grant(engine, _cleanup_test_perms):
    """Every newly seeded permission lands on super_admin, even with
    no explicit grant — mirrors the seed pattern in migration 0001."""
    code = f"{_TEST_PERM_PREFIX}auto_super"
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await seed_permissions(s, [code])
        await s.commit()

    async with factory() as s:
        super_id = (
            await s.execute(
                select(Role.id).where(Role.code == "super_admin")
            )
        ).scalar_one()
        rows = (
            await s.execute(
                select(role_permissions).where(
                    role_permissions.c.permission_code == code,
                    role_permissions.c.role_id == super_id,
                )
            )
        ).all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_unknown_role_is_skipped(engine, _cleanup_test_perms, caplog):
    """A grant on a role that doesn't exist logs a warning and moves
    on — host apps may opt into a smaller role set than atrium ships."""
    code = f"{_TEST_PERM_PREFIX}unknown_role"
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await seed_permissions(
            s,
            [code],
            grants={"definitely_not_a_real_role": [code]},
        )
        await s.commit()

    async with factory() as s:
        # The permission landed (and super_admin got it), but no
        # role_permissions row references the bogus role.
        bogus = (
            await s.execute(
                select(role_permissions).where(
                    role_permissions.c.permission_code == code,
                )
            )
        ).all()
    # Only the super_admin auto-grant — the unknown role contributed
    # nothing.
    assert len(bogus) == 1


def test_seed_permissions_sync(mysql_url, _cleanup_test_perms_sync):
    """The sync sibling walks the same SQL inside an alembic migration.
    Uses a short-lived sync engine matching the alembic ``op.get_bind()``
    contract."""
    code = f"{_TEST_PERM_PREFIX}sync"
    sync_url = mysql_url.replace("mysql+aiomysql://", "mysql+pymysql://", 1)
    sync_engine = create_engine(sync_url, pool_pre_ping=True)
    try:
        with sync_engine.begin() as conn:
            seed_permissions_sync(conn, [code], grants={"admin": [code]})
            seed_permissions_sync(conn, [code], grants={"admin": [code]})

        with sync_engine.connect() as conn:
            perm_rows = conn.execute(
                text("SELECT code FROM permissions WHERE code = :c"),
                {"c": code},
            ).all()
            grant_rows = conn.execute(
                text(
                    "SELECT 1 FROM role_permissions rp "
                    "JOIN roles r ON r.id = rp.role_id "
                    "WHERE rp.permission_code = :c"
                ),
                {"c": code},
            ).all()
    finally:
        sync_engine.dispose()

    # admin grant + super_admin auto-grant.
    assert len(perm_rows) == 1
    assert len(grant_rows) == 2


@pytest.fixture
def _cleanup_test_perms_sync(mysql_url):
    yield
    sync_url = mysql_url.replace("mysql+aiomysql://", "mysql+pymysql://", 1)
    sync_engine = create_engine(sync_url, pool_pre_ping=True)
    try:
        with sync_engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM role_permissions "
                    "WHERE permission_code LIKE :prefix"
                ),
                {"prefix": f"{_TEST_PERM_PREFIX}%"},
            )
            conn.execute(
                text("DELETE FROM permissions WHERE code LIKE :prefix"),
                {"prefix": f"{_TEST_PERM_PREFIX}%"},
            )
    finally:
        sync_engine.dispose()
