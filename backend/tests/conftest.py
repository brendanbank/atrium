# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Test fixtures — real MySQL via testcontainers.

A single MySQL container is started for the whole session; tests get
a transactional session that is rolled back after each test so DB state
stays clean without re-running Alembic between tests.

If a DATABASE_URL env var is provided (e.g., CI has MySQL running as a
service), we use that instead of starting a container.
"""
from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config as AlembicConfig
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.mysql import MySqlContainer

from alembic import command
from app.db import Base, get_session
from app.main import create_app


def _alembic_upgrade(sync_url: str) -> None:
    cfg = AlembicConfig("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", sync_url)
    cfg.set_main_option("script_location", "alembic")
    command.upgrade(cfg, "head")


async def _reseed_rbac(engine: AsyncEngine) -> None:
    """Re-populate the ``roles`` and ``role_permissions`` tables with
    the migration-baseline seed state.

    Admin tests legitimately mutate role membership (permission toggles,
    custom roles). Running this after each test isolates fixtures:
    every test observes the same baseline regardless of what the
    previous test did.

    Atrium ships three system roles:
      - ``super_admin``: every permission, including ``user.impersonate``
      - ``admin``: every permission except ``user.impersonate``
      - ``user``: no permissions (host apps grant their own)

    Permissions themselves are invariant (seeded once by migration), so
    we keep them untouched.
    """
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO roles (code, name, is_system) VALUES
                  ('admin', 'Admin', TRUE),
                  ('super_admin', 'Super admin', TRUE),
                  ('user', 'User', TRUE)
                """
            )
        )
        # super_admin → everything (including user.impersonate).
        await conn.execute(
            text(
                """
                INSERT INTO role_permissions (role_id, permission_code)
                SELECT r.id, p.code FROM roles r, permissions p
                WHERE r.code = 'super_admin'
                """
            )
        )
        # admin → everything except user.impersonate. The privilege-
        # escalation guard in admin_users.update prevents a plain admin
        # from self-promoting to super_admin.
        await conn.execute(
            text(
                """
                INSERT INTO role_permissions (role_id, permission_code)
                SELECT r.id, p.code FROM roles r, permissions p
                WHERE r.code = 'admin' AND p.code != 'user.impersonate'
                """
            )
        )


@pytest.fixture(scope="session")
def mysql_url() -> str:
    """Return an async DSN pointing at a MySQL instance.

    Prefers DATABASE_URL from the env (CI); otherwise spins up a
    throw-away container. The container lifetime is the test session."""
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        yield env_url
        return

    with MySqlContainer("mysql:8.0") as mysql:
        # testcontainers 4.x returns a driver-less ``mysql://...`` URL.
        # SQLAlchemy then defaults to the MySQLdb driver which we don't
        # install. Force aiomysql here; run_migrations below flips to
        # pymysql for the sync alembic upgrade.
        raw_url = mysql.get_connection_url()
        async_url = raw_url.replace("mysql://", "mysql+aiomysql://", 1)
        yield async_url


@pytest.fixture(scope="session", autouse=True)
def run_migrations(mysql_url: str) -> None:
    """Run Alembic once per session against the test DB.

    ``alembic/env.py`` calls ``asyncio.run(run_async_migrations())``
    and builds an async engine, so pass the aiomysql URL through —
    rewriting to ``mysql+pymysql`` (sync) here would explode with
    "asyncio extension requires an async driver"."""
    _alembic_upgrade(mysql_url)


@pytest.fixture(autouse=True)
def _bind_middleware_to_test_engine(monkeypatch, engine, mysql_url):
    """The maintenance middleware (and any future middleware that
    talks to the DB) bypasses FastAPI's dependency injection and
    grabs ``app.db.get_session_factory()`` directly, which is bound
    to the ``.env`` DSN ("mysql" hostname, only resolvable inside the
    docker compose network). Repoint the references to the test
    engine so middleware reads the same DB the request would.

    Also wipes ``app_settings['system']`` after each test so a stuck
    maintenance flag from a prior test doesn't 503 the rest of the
    suite. ``app_settings`` is in the conftest truncate-skip list, so
    flags otherwise persist across tests. The wipe runs through a
    short-lived sync engine to dodge the cross-test event-loop
    lifecycle that ``async_sessionmaker`` would tangle with.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services import captcha as captcha_module
    from app.services import maintenance as maintenance_module

    test_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(
        maintenance_module, "get_session_factory", lambda: test_factory
    )
    # The captcha middleware reads ``auth.captcha_provider`` from
    # app_settings on every gated request. Same shape as maintenance
    # — repoint at the test engine so the lookup hits the test DB.
    monkeypatch.setattr(
        captcha_module, "get_session_factory", lambda: test_factory
    )
    maintenance_module.reset_cache()
    yield

    sync_url = mysql_url.replace("mysql+aiomysql://", "mysql+pymysql://", 1)
    sync_engine = create_engine(sync_url, pool_pre_ping=True)
    try:
        with sync_engine.begin() as conn:
            # Wipe every namespace a middleware reads on the hot path —
            # ``system`` (maintenance) and ``auth`` (captcha provider).
            # Tests that need a specific value re-set it inside the test
            # body; this teardown stops a stuck flag from poisoning the
            # rest of the suite.
            conn.execute(
                text("DELETE FROM app_settings WHERE `key` IN ('system', 'auth')")
            )
    finally:
        sync_engine.dispose()
    maintenance_module.reset_cache()


@pytest.fixture(autouse=True)
def _auto_pass_2fa(monkeypatch, request):
    """Make every freshly-issued ``AuthSession`` row full-access
    (``totp_passed=True``) by default so tests that just need an
    authenticated actor don't have to drive the TOTP / email-OTP
    dance on every login.

    Tests that specifically exercise the 2FA flow (TOTP setup /
    confirm / verify, email-OTP the same, admin reset behaviour
    around partial sessions) opt back into the real gate with
    ``@pytest.mark.real_2fa``.
    """
    if "real_2fa" in request.keywords:
        return

    from sqlalchemy import update

    from app.auth import backend as auth_backend
    from app.models.auth_session import AuthSession

    original_write = auth_backend.DBSessionJWTStrategy.write_token

    async def _patched(self, user):
        token = await original_write(self, user)
        await self._session.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == user.id,
                AuthSession.revoked_at.is_(None),
            )
            .values(totp_passed=True)
        )
        await self._session.commit()
        return token

    monkeypatch.setattr(
        auth_backend.DBSessionJWTStrategy, "write_token", _patched
    )


@pytest_asyncio.fixture
async def engine(mysql_url: str) -> AsyncGenerator[AsyncEngine, None]:
    eng = create_async_engine(mysql_url, pool_pre_ping=True, future=True)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Per-test session. Tables are TRUNCATED after each test to isolate
    state — simpler and more portable than SAVEPOINT tricks on MySQL."""
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as s:
        yield s

    # Clean up after the test.
    async with engine.begin() as conn:
        await conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in {
                "app_settings",
                "email_templates",
                # ``permissions`` is seeded once by migration and never
                # modified by code — safe to keep. ``roles`` +
                # ``role_permissions`` ARE modified by admin tests
                # (system-role permission edits), so truncate + re-seed
                # them per test to keep isolation.
                "permissions",
            }:
                continue  # seeded rows we keep
            await conn.execute(text(f"TRUNCATE TABLE `{table.name}`"))
        await conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    await _reseed_rbac(engine)


@pytest_asyncio.fixture
async def client(engine: AsyncEngine) -> AsyncGenerator[httpx.AsyncClient, None]:
    """HTTP client with DB override bound to the test engine."""
    app = create_app()

    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    async def _override_get_session():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _override_get_session

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as c:
        yield c

    # Clean up DB state.
    async with engine.begin() as conn:
        await conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in {
                "properties",
                "app_settings",
                "email_templates",
                "reminder_rules",
                "permissions",
            }:
                continue
            await conn.execute(text(f"TRUNCATE TABLE `{table.name}`"))
        await conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    await _reseed_rbac(engine)
