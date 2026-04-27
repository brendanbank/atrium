# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the maintenance-mode middleware.

Three things to pin:

* Off by default — every endpoint serves normally.
* On → 503 for anyone who isn't on the bypass list and isn't a
  super_admin. The 503 carries ``code: "maintenance_mode"`` so the
  frontend can switch to its maintenance page.
* On → super_admin still gets through (otherwise they couldn't flip
  the flag back from the admin UI).
"""
from __future__ import annotations

import pytest
from sqlalchemy import delete
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.ops import AppSetting
from app.services.maintenance import reset_cache
from tests.helpers import login, seed_admin, seed_super_admin, seed_user


async def _set_maintenance(engine, *, on: bool, message: str = "Be back soon.") -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        stmt = mysql_insert(AppSetting).values(
            key="system",
            value={
                "maintenance_mode": on,
                "maintenance_message": message,
                "announcement": None,
                "announcement_level": "info",
            },
        )
        stmt = stmt.on_duplicate_key_update(value=stmt.inserted.value)
        await s.execute(stmt)
        await s.commit()
    reset_cache()


async def _wipe(engine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await s.execute(delete(AppSetting).where(AppSetting.key == "system"))
        await s.commit()
    reset_cache()


# Middleware-engine binding is autouse-installed in tests/conftest.py.


@pytest.mark.asyncio
async def test_off_by_default_routes_serve_normally(client, engine):
    await _wipe(engine)
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)
    r = await client.get("/users/me/context")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_on_blocks_anonymous_with_503(client, engine):
    await _set_maintenance(engine, on=True)
    r = await client.get("/admin/roles")
    assert r.status_code == 503
    body = r.json()
    assert body["code"] == "maintenance_mode"
    assert body["message"] == "Be back soon."


@pytest.mark.asyncio
async def test_on_blocks_normal_users(client, engine):
    user = await seed_user(engine)
    await login(client, user.email, "user-pw-123", engine=engine)
    await _set_maintenance(engine, on=True)
    r = await client.get("/notifications/")
    # Normal user is not on the bypass list — gets the 503.
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_on_blocks_admin_who_is_not_super_admin(client, engine):
    """Plain admin doesn't bypass — only super_admin does. Otherwise
    a comprised admin token could keep using the API during a
    maintenance window."""
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)
    await _set_maintenance(engine, on=True)
    r = await client.get("/admin/roles")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_on_super_admin_passes_through(client, engine):
    super_a = await seed_super_admin(engine)
    await login(client, super_a.email, "super-pw-123", engine=engine)
    await _set_maintenance(engine, on=True)
    r = await client.get("/admin/roles")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_on_app_config_endpoint_still_reachable(client, engine):
    """/app-config must answer even during maintenance — the frontend
    fetches it to render the maintenance page itself, otherwise the
    UI gets stuck spinning."""
    await _set_maintenance(engine, on=True)
    r = await client.get("/app-config")
    assert r.status_code == 200
    assert r.json()["system"]["maintenance_mode"] is True


@pytest.mark.asyncio
async def test_on_health_endpoints_still_reachable(client, engine):
    await _set_maintenance(engine, on=True)
    for path in ("/healthz", "/readyz"):
        r = await client.get(path)
        assert r.status_code == 200, path


@pytest.mark.asyncio
async def test_on_login_endpoint_still_reachable(client, engine):
    """Super-admin recovery path — must be able to sign in to flip the
    flag back from the admin UI."""
    super_a = await seed_super_admin(engine)
    await _set_maintenance(engine, on=True)
    r = await client.post(
        "/auth/jwt/login",
        data={"username": super_a.email, "password": "super-pw-123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code in (200, 204), r.text
