# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Issue #178 — the OpenAPI schema + Swagger/ReDoc UIs must not be
served to anonymous callers in prod.

A black-box scan of a prod deployment pulled the full internal route
map (228 endpoints, every admin route) from an unauthenticated
``/openapi.json``. In prod those endpoints are constructed with
``openapi_url``/``docs_url``/``redoc_url`` set to ``None`` and re-mounted
behind ``require_admin``. Dev keeps them open for DX.

These tests build the app directly (no ``/api`` prefix wrapper) because
the docs live at the un-prefixed root, and toggle ``ENVIRONMENT`` per
case. ``get_settings`` is ``lru_cache``-d, so each helper clears the
cache on the way in and out.
"""
from __future__ import annotations

import contextlib

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import get_session
from app.main import create_app
from app.settings import get_settings
from tests.helpers import seed_admin, seed_user


@contextlib.asynccontextmanager
async def _client_for_env(engine, environment, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", environment)
    if environment == "prod":
        # ``_prod_sanity`` refuses to boot with the dev-default secrets.
        monkeypatch.setenv("APP_SECRET_KEY", "prod-secret-not-the-default")
        monkeypatch.setenv("JWT_SECRET", "prod-jwt-not-the-default")
    get_settings.cache_clear()
    try:
        app = create_app()
        factory = async_sessionmaker(
            engine, expire_on_commit=False, autoflush=False
        )

        async def _override_get_session():
            async with factory() as s:
                yield s

        app.dependency_overrides[get_session] = _override_get_session
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as c:
            yield c
    finally:
        # Drop the prod-flavoured Settings so the rest of the suite sees
        # the dev defaults again.
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_docs_open_in_dev(engine, monkeypatch):
    async with _client_for_env(engine, "dev", monkeypatch) as client:
        r = await client.get("/openapi.json")
        assert r.status_code == 200, r.text
        assert "openapi" in r.json()
        assert (await client.get("/docs")).status_code == 200


@pytest.mark.asyncio
async def test_docs_gated_for_anonymous_in_prod(engine, monkeypatch):
    async with _client_for_env(engine, "prod", monkeypatch) as client:
        for path in ("/openapi.json", "/docs", "/redoc"):
            r = await client.get(path)
            assert r.status_code == 401, (path, r.status_code, r.text)


@pytest.mark.asyncio
async def test_docs_gated_for_non_admin_in_prod(engine, monkeypatch):
    user = await seed_user(engine)
    async with _client_for_env(engine, "prod", monkeypatch) as client:
        r = await client.post(
            "/api/auth/jwt/login",
            data={"username": user.email, "password": "user-pw-123"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code in (200, 204), r.text
        # Authenticated but lacks the admin role → 403, not 401.
        assert (await client.get("/openapi.json")).status_code == 403


@pytest.mark.asyncio
async def test_docs_accessible_to_admin_in_prod(engine, monkeypatch):
    admin = await seed_admin(engine)
    async with _client_for_env(engine, "prod", monkeypatch) as client:
        r = await client.post(
            "/api/auth/jwt/login",
            data={"username": admin.email, "password": "admin-pw-123"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code in (200, 204), r.text

        schema = await client.get("/openapi.json")
        assert schema.status_code == 200, schema.text
        assert "openapi" in schema.json()

        docs = await client.get("/docs")
        assert docs.status_code == 200
        assert "swagger-ui" in docs.text.lower()
