# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause
import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db import get_session
from app.main import create_app


async def test_healthz_ok(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_healthz_explicit_api_prefix(client):
    """The prefix wrapper is idempotent — passing the full ``/api/...``
    path still resolves to the same route."""
    r = await client.get("/api/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest_asyncio.fixture
async def _raw_client(engine: AsyncEngine):
    """Bypass the test fixture's API-prefix wrapper so we can verify
    the un-prefixed URL space really is owned by the SPA mount (and
    returns 404 here — no static dir is configured in unit tests)."""
    app = create_app()
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    async def _override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as c:
        yield c


async def test_healthz_unprefixed_404(_raw_client):
    """``/healthz`` without the ``/api`` prefix must NOT match the API
    route — the SPA owns un-prefixed URL space (issue #89)."""
    r = await _raw_client.get("/healthz")
    assert r.status_code == 404
