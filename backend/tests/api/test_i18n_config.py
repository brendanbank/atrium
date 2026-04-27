# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the ``i18n`` app-config namespace.

Phase 9 ships locale enablement plus per-locale string overrides
through the same ``app_settings`` plumbing as ``brand``. These tests
pin:

* ``GET /app-config`` (public) includes the namespace with sensible
  defaults — the frontend consumes it at boot to drive the language
  switcher and merge admin overrides.
* ``GET /admin/app-config`` returns the namespace, gated on
  ``app_setting.manage`` like every other admin app-config route.
* ``PUT /admin/app-config/i18n`` round-trips the dict-of-dicts shape
  and validates it.
"""
from __future__ import annotations

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.ops import AppSetting
from tests.helpers import login, seed_admin, seed_user


async def _wipe(engine, *keys: str) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await s.execute(delete(AppSetting).where(AppSetting.key.in_(keys)))
        await s.commit()


@pytest.mark.asyncio
async def test_public_endpoint_includes_i18n_defaults(client, engine):
    await _wipe(engine, "i18n")
    r = await client.get("/app-config")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "i18n" in body
    cfg = body["i18n"]
    assert cfg["enabled_locales"] == ["en", "nl"]
    assert cfg["overrides"] == {}


@pytest.mark.asyncio
async def test_admin_can_round_trip_i18n_namespace(client, engine):
    await _wipe(engine, "i18n")
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)
    payload = {
        "enabled_locales": ["en", "nl", "de", "fr"],
        "overrides": {
            "en": {"login.submit": "Sign in"},
            "nl": {"login.submit": "Aanmelden"},
        },
    }
    r = await client.put("/admin/app-config/i18n", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled_locales"] == ["en", "nl", "de", "fr"]
    assert body["overrides"]["en"]["login.submit"] == "Sign in"
    assert body["overrides"]["nl"]["login.submit"] == "Aanmelden"

    r2 = await client.get("/app-config")
    assert r2.status_code == 200
    assert r2.json()["i18n"]["overrides"]["nl"]["login.submit"] == "Aanmelden"


@pytest.mark.asyncio
async def test_admin_endpoint_requires_app_setting_manage(client, engine):
    user = await seed_user(engine)
    await login(client, user.email, "user-pw-123", engine=engine)
    r = await client.put(
        "/admin/app-config/i18n",
        json={"enabled_locales": ["en"], "overrides": {}},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_invalid_overrides_shape_rejected(client, engine):
    await _wipe(engine, "i18n")
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)
    # ``overrides`` must be dict[str, dict[str, str]] — a plain string
    # value at the locale level should fail validation.
    r = await client.put(
        "/admin/app-config/i18n",
        json={"enabled_locales": ["en"], "overrides": {"en": "not-a-dict"}},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_partial_payload_resets_unset_fields(client, engine):
    """Same Pydantic-default behaviour as the brand namespace — a PUT
    with only ``enabled_locales`` reverts ``overrides`` to its default
    empty dict, because the admin UI always submits the full shape."""
    await _wipe(engine, "i18n")
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)
    r = await client.put(
        "/admin/app-config/i18n",
        json={
            "enabled_locales": ["en", "fr"],
            "overrides": {"fr": {"common.save": "Enregistrer"}},
        },
    )
    assert r.status_code == 200

    r2 = await client.put(
        "/admin/app-config/i18n",
        json={"enabled_locales": ["en"]},
    )
    assert r2.status_code == 200
    assert r2.json()["overrides"] == {}
