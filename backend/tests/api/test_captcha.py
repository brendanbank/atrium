# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Coverage for the pluggable CAPTCHA gate (Phase 4).

Pinned behaviours:

* ``provider=none``: the helper never touches the network and the
  register/login/forgot-password endpoints proceed without a token.
* ``provider=turnstile`` and ``provider=hcaptcha``: register requires
  a token, missing/invalid → 400, valid (mocked siteverify) → 204.
* The login middleware short-circuits ``POST /auth/jwt/login`` and
  ``POST /auth/forgot-password`` on a missing/invalid token.
* ``CAPTCHA_SECRET`` empty + provider on: fail-open with a warning.
* siteverify network error: fail-open.
"""
from __future__ import annotations

import pytest
from sqlalchemy import delete
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.ops import AppSetting
from tests.helpers import seed_user


async def _set_auth_config(engine, payload: dict) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        stmt = mysql_insert(AppSetting).values(key="auth", value=payload)
        stmt = stmt.on_duplicate_key_update(value=stmt.inserted.value)
        await s.execute(stmt)
        await s.commit()


async def _wipe_auth_config(engine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await s.execute(delete(AppSetting).where(AppSetting.key == "auth"))
        await s.commit()


def _captcha_config(*, provider: str, site_key: str | None = "site-key-x") -> dict:
    return {
        "allow_self_delete": True,
        "delete_grace_days": 30,
        "allow_signup": True,
        "signup_default_role_code": "user",
        "require_email_verification": False,
        "password_min_length": 8,
        "password_require_mixed_case": False,
        "password_require_digit": False,
        "password_require_symbol": False,
        "password_check_breach": False,
        "require_2fa_for_roles": [],
        "captcha_provider": provider,
        "captcha_site_key": site_key,
    }


@pytest.fixture(autouse=True)
def _set_captcha_secret(monkeypatch):
    """Default test fixture: a non-empty ``captcha_secret`` so the
    fail-open-on-empty-secret branch isn't accidentally exercised by
    every test. Patch the cached Settings instance directly rather
    than clearing the cache — clearing would force a fresh
    ``Settings()`` read and break the test engine binding (the cached
    instance carries the testcontainers DSN)."""
    from app.settings import get_settings

    monkeypatch.setattr(get_settings(), "captcha_secret", "test-secret")
    yield


@pytest.mark.asyncio
async def test_provider_none_register_no_token_required(client, engine):
    """Default provider is ``none`` — register works without a token."""
    await _wipe_auth_config(engine)
    await _set_auth_config(engine, _captcha_config(provider="none"))
    r = await client.post(
        "/auth/register",
        json={
            "email": "noprov@example.com",
            "password": "fresh-pw-12345",
            "full_name": "N",
        },
    )
    assert r.status_code == 204, r.text


@pytest.mark.asyncio
async def test_provider_none_login_no_token_required(client, engine):
    """Login still works when provider is off — the middleware
    short-circuits to the no-op path."""
    await _wipe_auth_config(engine)
    await _set_auth_config(engine, _captcha_config(provider="none"))
    await seed_user(engine, email="login-noprov@example.com", password="user-pw-123")
    r = await client.post(
        "/auth/jwt/login",
        data={"username": "login-noprov@example.com", "password": "user-pw-123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code in (200, 204), r.text


@pytest.mark.asyncio
async def test_turnstile_missing_token_register_400(client, engine):
    await _set_auth_config(engine, _captcha_config(provider="turnstile"))
    r = await client.post(
        "/auth/register",
        json={
            "email": "miss@example.com",
            "password": "fresh-pw-12345",
            "full_name": "M",
        },
    )
    assert r.status_code == 400
    assert "captcha" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_turnstile_invalid_token_register_400(client, engine, monkeypatch):
    """A token the upstream rejects with ``success: false`` produces a 400."""
    from app.services import captcha as captcha_module

    class _FakeResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"success": False, "error-codes": ["invalid-input-response"]}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, data):
            return _FakeResp()

    monkeypatch.setattr(captcha_module.httpx, "AsyncClient", _FakeClient)

    await _set_auth_config(engine, _captcha_config(provider="turnstile"))
    r = await client.post(
        "/auth/register",
        json={
            "email": "bad@example.com",
            "password": "fresh-pw-12345",
            "full_name": "B",
            "captcha_token": "made-up",
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_turnstile_valid_token_register_204(client, engine, monkeypatch):
    from app.services import captcha as captcha_module

    class _FakeResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"success": True}

    posted: dict[str, object] = {}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, data):
            posted["url"] = url
            posted["data"] = data
            return _FakeResp()

    monkeypatch.setattr(captcha_module.httpx, "AsyncClient", _FakeClient)

    await _set_auth_config(engine, _captcha_config(provider="turnstile"))
    r = await client.post(
        "/auth/register",
        json={
            "email": "good@example.com",
            "password": "fresh-pw-12345",
            "full_name": "G",
            "captcha_token": "valid-token",
        },
    )
    assert r.status_code == 204, r.text
    assert "challenges.cloudflare.com" in str(posted["url"])
    assert posted["data"] == {"secret": "test-secret", "response": "valid-token"}


@pytest.mark.asyncio
async def test_hcaptcha_missing_token_register_400(client, engine):
    await _set_auth_config(engine, _captcha_config(provider="hcaptcha"))
    r = await client.post(
        "/auth/register",
        json={
            "email": "hmiss@example.com",
            "password": "fresh-pw-12345",
            "full_name": "H",
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_hcaptcha_valid_token_register_204(client, engine, monkeypatch):
    from app.services import captcha as captcha_module

    class _FakeResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"success": True}

    posted: dict[str, object] = {}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, data):
            posted["url"] = url
            posted["data"] = data
            return _FakeResp()

    monkeypatch.setattr(captcha_module.httpx, "AsyncClient", _FakeClient)

    await _set_auth_config(engine, _captcha_config(provider="hcaptcha"))
    r = await client.post(
        "/auth/register",
        json={
            "email": "hgood@example.com",
            "password": "fresh-pw-12345",
            "full_name": "HG",
            "captcha_token": "h-valid",
        },
    )
    assert r.status_code == 204, r.text
    assert "hcaptcha.com" in str(posted["url"])


@pytest.mark.asyncio
async def test_empty_secret_fails_open(client, engine, monkeypatch):
    """When provider is on but ``captcha_secret`` is empty, the
    verifier fails open with a warning so a misconfigured deploy
    doesn't lock everyone out."""
    from app.settings import get_settings

    monkeypatch.setattr(get_settings(), "captcha_secret", "")

    await _set_auth_config(engine, _captcha_config(provider="turnstile"))
    r = await client.post(
        "/auth/register",
        json={
            "email": "open-secret@example.com",
            "password": "fresh-pw-12345",
            "full_name": "O",
            "captcha_token": "anything",
        },
    )
    assert r.status_code == 204, r.text


@pytest.mark.asyncio
async def test_network_error_fails_open(client, engine, monkeypatch):
    """An exception talking to the siteverify upstream falls back to
    fail-open. Same posture as the HIBP integration."""
    from app.services import captcha as captcha_module

    class _BoomClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, data):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(captcha_module.httpx, "AsyncClient", _BoomClient)

    await _set_auth_config(engine, _captcha_config(provider="turnstile"))
    r = await client.post(
        "/auth/register",
        json={
            "email": "neterr@example.com",
            "password": "fresh-pw-12345",
            "full_name": "N",
            "captcha_token": "any",
        },
    )
    assert r.status_code == 204, r.text


@pytest.mark.asyncio
async def test_login_missing_token_returns_400(client, engine):
    """Login is form-encoded — fastapi-users owns the route, so the
    captcha gate runs in the middleware. Missing token → 400."""
    await _set_auth_config(engine, _captcha_config(provider="turnstile"))
    await seed_user(engine, email="login-miss@example.com", password="user-pw-123")

    r = await client.post(
        "/auth/jwt/login",
        data={"username": "login-miss@example.com", "password": "user-pw-123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 400
    assert "captcha" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_valid_token_succeeds(client, engine, monkeypatch):
    """A valid captcha token plus correct credentials lets the login
    proceed — confirms the middleware re-emits the form body so
    fastapi-users still sees the username/password fields."""
    from app.services import captcha as captcha_module

    class _OkResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"success": True}

    class _OkClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, data):
            return _OkResp()

    monkeypatch.setattr(captcha_module.httpx, "AsyncClient", _OkClient)

    await _set_auth_config(engine, _captcha_config(provider="turnstile"))
    await seed_user(engine, email="login-ok@example.com", password="user-pw-123")

    r = await client.post(
        "/auth/jwt/login",
        data={
            "username": "login-ok@example.com",
            "password": "user-pw-123",
            "captcha_token": "ok-token",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code in (200, 204), r.text


@pytest.mark.asyncio
async def test_forgot_password_missing_token_returns_400(client, engine):
    """forgot-password is JSON. The middleware reads ``captcha_token``
    from the JSON body."""
    await _set_auth_config(engine, _captcha_config(provider="turnstile"))
    r = await client.post(
        "/auth/forgot-password", json={"email": "anyone@example.com"}
    )
    assert r.status_code == 400
    assert "captcha" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_forgot_password_valid_token_succeeds(client, engine, monkeypatch):
    from app.services import captcha as captcha_module

    class _OkResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"success": True}

    class _OkClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, data):
            return _OkResp()

    monkeypatch.setattr(captcha_module.httpx, "AsyncClient", _OkClient)

    await _set_auth_config(engine, _captcha_config(provider="turnstile"))
    # No actual user needed — fastapi-users returns 202 regardless to
    # avoid email enumeration. We just need the captcha gate to pass
    # and the request to reach the route.
    r = await client.post(
        "/auth/forgot-password",
        json={"email": "any@example.com", "captcha_token": "valid"},
    )
    assert r.status_code in (200, 202), r.text


@pytest.mark.asyncio
async def test_public_appconfig_exposes_captcha(client, engine):
    """The public app-config bundle surfaces provider + site_key so
    the frontend widget can render. The full AuthConfig stays admin-
    only; the secret is never in the bundle (it's an env var)."""
    await _set_auth_config(
        engine,
        _captcha_config(provider="turnstile", site_key="public-key-123"),
    )
    r = await client.get("/app-config")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["auth"]["captcha_provider"] == "turnstile"
    assert body["auth"]["captcha_site_key"] == "public-key-123"
    # Sanity: the secret never leaks.
    assert "captcha_secret" not in body["auth"]
