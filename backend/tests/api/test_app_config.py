# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the app-config endpoints.

Three surfaces to pin:

* ``GET /app-config`` — public, returns only namespaces marked
  ``public=True`` in ``services.app_config.NAMESPACES``. Unknown / not
  yet written namespaces fall back to the Pydantic model defaults.
* ``GET /admin/app-config`` — gated on ``app_setting.manage``;
  returns every namespace including admin-only ones.
* ``PUT /admin/app-config/{namespace}`` — Pydantic-validated write,
  records an audit row, returns the canonicalised value.

The conftest ``client`` fixture preserves ``app_settings`` across
tests, so each test deletes the namespaces it touches up-front to keep
isolation.
"""
from __future__ import annotations

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.ops import AppSetting
from tests.helpers import login, seed_admin, seed_user


async def _wipe_app_config(engine, *keys: str) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await s.execute(delete(AppSetting).where(AppSetting.key.in_(keys)))
        await s.commit()


@pytest.mark.asyncio
async def test_public_endpoint_includes_version(client, engine):
    """Issue #43 — top-level ``version`` lets host bundles mirror the
    running atrium release onto ``window.__ATRIUM_VERSION__``.

    Issue #57 — the published runtime image doesn't install
    ``atrium-backend`` as a distribution, so ``importlib.metadata``
    returned ``"unknown"`` and the feature silently regressed. Pin the
    value against ``pyproject.toml`` so any future dist-metadata
    breakage shows up in CI instead of in production.
    """
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    with pyproject.open("rb") as fh:
        expected = tomllib.load(fh)["project"]["version"]

    r = await client.get("/app-config")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "version" in body, body
    assert isinstance(body["version"], str)
    assert body["version"] != "unknown", (
        "atrium version resolution fell through to 'unknown' — "
        "host-bundle feature detection (window.__ATRIUM_VERSION__) is "
        "broken. See issue #57."
    )
    assert body["version"] == expected, (body["version"], expected)


@pytest.mark.asyncio
async def test_public_endpoint_returns_brand_defaults(client, engine):
    await _wipe_app_config(engine, "brand")
    r = await client.get("/app-config")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "brand" in body
    brand = body["brand"]
    assert brand["name"] == "Atrium"
    assert brand["preset"] == "default"
    assert brand["overrides"] == {}
    assert brand["logo_url"] == "/logo.svg"
    assert brand["support_email"] is None


@pytest.mark.asyncio
async def test_public_endpoint_requires_no_auth(client, engine):
    await _wipe_app_config(engine, "brand")
    # No login, no cookies — anon should still get the bundle.
    r = await client.get("/app-config")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_admin_endpoint_requires_app_setting_manage(client, engine):
    user = await seed_user(engine)
    await login(client, user.email, "user-pw-123", engine=engine)
    r = await client.get("/admin/app-config")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_endpoint_returns_every_namespace(client, engine):
    await _wipe_app_config(engine, "brand")
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)
    r = await client.get("/admin/app-config")
    assert r.status_code == 200, r.text
    body = r.json()
    # Phase 0 only registers ``brand``; future phases extend it.
    assert "brand" in body


@pytest.mark.asyncio
async def test_admin_can_write_brand(client, engine):
    await _wipe_app_config(engine, "brand")
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)
    r = await client.put(
        "/admin/app-config/brand",
        json={
            "name": "Casa Del Leone",
            "preset": "classic",
            "logo_url": "/brand/casa.svg",
            "support_email": "help@example.com",
            "overrides": {"primaryColor": "blue"},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Casa Del Leone"
    assert body["preset"] == "classic"
    assert body["overrides"] == {"primaryColor": "blue"}

    # Round-trip through the public endpoint.
    r2 = await client.get("/app-config")
    assert r2.json()["brand"]["name"] == "Casa Del Leone"


@pytest.mark.asyncio
async def test_admin_write_rejects_unknown_preset(client, engine):
    await _wipe_app_config(engine, "brand")
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)
    r = await client.put(
        "/admin/app-config/brand",
        json={"preset": "neon-pink"},
    )
    # Pydantic Literal mismatch — surfaced as 400 by the route.
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_admin_write_unknown_namespace_404(client, engine):
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)
    r = await client.put("/admin/app-config/not-a-namespace", json={})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_partial_brand_payload_keeps_defaults_for_unset(client, engine):
    """Pydantic re-applies defaults for any field omitted from the
    payload — so PUTting just ``{"name": "X"}`` resets preset to
    'default' rather than preserving a previous 'classic'. This is
    intentional: the admin UI always sends the full namespace shape."""
    await _wipe_app_config(engine, "brand")
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)
    r = await client.put(
        "/admin/app-config/brand",
        json={"name": "Just A Name"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Just A Name"
    assert body["preset"] == "default"
