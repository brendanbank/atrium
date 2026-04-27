# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Password-policy + 2FA-enforcement coverage (Phase 3).

Driven through ``POST /auth/register`` because that's the realistic
public-facing entry point — invite accept and admin password-reset go
through ``UserManager.validate_password`` separately, and the underlying
helper is shared, so the register surface exercises the same code path.

The end-to-end 2FA enrollment test seeds a user with the ``admin`` role,
flips ``auth.require_2fa_for_roles=['admin']``, and asserts the
``/users/me/context`` endpoint returns 403 with
``code: 2fa_enrollment_required``. Adding a confirmed UserTOTP row
clears the gate.
"""
from __future__ import annotations

import pytest
from sqlalchemy import delete, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.auth import User
from app.models.ops import AppSetting
from app.models.user_totp import UserTOTP
from tests.helpers import login, seed_admin


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


def _base_signup_config(**overrides) -> dict:
    cfg = {
        "allow_self_delete": True,
        "delete_grace_days": 30,
        "allow_signup": True,
        "signup_default_role_code": "user",
        "require_email_verification": True,
        "password_min_length": 8,
        "password_require_mixed_case": False,
        "password_require_digit": False,
        "password_require_symbol": False,
        "password_check_breach": False,
        "require_2fa_for_roles": [],
    }
    cfg.update(overrides)
    return cfg


async def _user_exists(engine, email: str) -> bool:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        return (
            await s.execute(select(User.id).where(User.email == email))
        ).scalar_one_or_none() is not None


@pytest.fixture(autouse=True)
def _clear_hibp_cache():
    """Wipe the in-memory HIBP cache between tests so a monkeypatch
    in one test doesn't bleed into another."""
    from app.services.password_policy import _reset_hibp_cache_for_tests

    _reset_hibp_cache_for_tests()
    yield
    _reset_hibp_cache_for_tests()


@pytest.mark.asyncio
async def test_min_length_default_rejects_short_password(client, engine):
    await _set_auth_config(engine, _base_signup_config())
    r = await client.post(
        "/auth/register",
        json={
            "email": "short@example.com",
            "password": "abc12",
            "full_name": "S",
        },
    )
    assert r.status_code == 400
    assert "8" in r.json()["detail"]
    assert not await _user_exists(engine, "short@example.com")


@pytest.mark.asyncio
async def test_min_length_configurable(client, engine):
    """Bumping the minimum to 12 rejects a 10-char password — the
    policy reads from app_settings, not a hardcoded constant."""
    await _set_auth_config(
        engine, _base_signup_config(password_min_length=12)
    )
    r = await client.post(
        "/auth/register",
        json={
            "email": "shortish@example.com",
            "password": "abcdef1234",  # 10 chars
            "full_name": "S",
        },
    )
    assert r.status_code == 400
    assert "12" in r.json()["detail"]


@pytest.mark.asyncio
async def test_mixed_case_required(client, engine):
    await _set_auth_config(
        engine, _base_signup_config(password_require_mixed_case=True)
    )
    bad = await client.post(
        "/auth/register",
        json={
            "email": "lower@example.com",
            "password": "all-lower-pass",
            "full_name": "L",
        },
    )
    assert bad.status_code == 400
    good = await client.post(
        "/auth/register",
        json={
            "email": "mixed@example.com",
            "password": "Mixed-Pass-1",
            "full_name": "M",
        },
    )
    assert good.status_code == 204, good.text


@pytest.mark.asyncio
async def test_digit_required(client, engine):
    await _set_auth_config(
        engine, _base_signup_config(password_require_digit=True)
    )
    bad = await client.post(
        "/auth/register",
        json={
            "email": "nodig@example.com",
            "password": "no-digits-here",
            "full_name": "N",
        },
    )
    assert bad.status_code == 400
    good = await client.post(
        "/auth/register",
        json={
            "email": "withdig@example.com",
            "password": "with-digit-1",
            "full_name": "W",
        },
    )
    assert good.status_code == 204, good.text


@pytest.mark.asyncio
async def test_symbol_required(client, engine):
    await _set_auth_config(
        engine, _base_signup_config(password_require_symbol=True)
    )
    bad = await client.post(
        "/auth/register",
        json={
            "email": "nosym@example.com",
            "password": "alphanum1234",
            "full_name": "N",
        },
    )
    assert bad.status_code == 400
    good = await client.post(
        "/auth/register",
        json={
            "email": "withsym@example.com",
            "password": "alphanum-1234!",
            "full_name": "W",
        },
    )
    assert good.status_code == 204, good.text


@pytest.mark.asyncio
async def test_hibp_breached_password_rejected(client, engine, monkeypatch):
    """Monkeypatch the HIBP range fetch to claim our SHA-1 suffix
    appears in the breach list — registration must 400."""
    import hashlib

    from app.services import password_policy as pp

    password = "needs-to-be-long-enough"
    digest = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    suffix = digest[5:]

    async def _fake_fetch(prefix: str) -> set[str]:
        return {suffix}

    monkeypatch.setattr(pp, "_hibp_suffixes_for_prefix", _fake_fetch)
    await _set_auth_config(
        engine, _base_signup_config(password_check_breach=True)
    )

    r = await client.post(
        "/auth/register",
        json={
            "email": "breached@example.com",
            "password": password,
            "full_name": "B",
        },
    )
    assert r.status_code == 400
    assert "breach" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_hibp_network_failure_fails_open(client, engine, monkeypatch):
    """When HIBP is unreachable, the helper returns ``None`` and the
    policy treats it as a pass — the alternative is a global
    registration outage on every HIBP hiccup."""
    from app.services import password_policy as pp

    async def _fake_fetch(prefix: str):
        return None  # simulate network failure path

    monkeypatch.setattr(pp, "_hibp_suffixes_for_prefix", _fake_fetch)
    await _set_auth_config(
        engine, _base_signup_config(password_check_breach=True)
    )

    r = await client.post(
        "/auth/register",
        json={
            "email": "open@example.com",
            "password": "needs-to-be-long-enough",
            "full_name": "O",
        },
    )
    assert r.status_code == 204, r.text


@pytest.mark.asyncio
async def test_hibp_disabled_skips_check(client, engine, monkeypatch):
    """With ``password_check_breach=False`` (the default), the HIBP
    fetcher must never be called — verifies we don't pay the network
    cost for tenants that haven't opted in."""
    from app.services import password_policy as pp

    called = {"hit": False}

    async def _fake_fetch(prefix: str):
        called["hit"] = True
        return None

    monkeypatch.setattr(pp, "_hibp_suffixes_for_prefix", _fake_fetch)
    await _set_auth_config(
        engine, _base_signup_config(password_check_breach=False)
    )

    r = await client.post(
        "/auth/register",
        json={
            "email": "noscan@example.com",
            "password": "needs-to-be-long-enough",
            "full_name": "N",
        },
    )
    assert r.status_code == 204, r.text
    assert called["hit"] is False


@pytest.mark.asyncio
async def test_2fa_enforcement_blocks_admin_without_factor(client, engine):
    """Seed an admin without 2FA, configure ``require_2fa_for_roles``
    to include ``admin``, and assert ``/users/me/context`` returns 403
    with ``2fa_enrollment_required``. After enrolling a confirmed
    UserTOTP, the same endpoint succeeds."""
    await _set_auth_config(
        engine, _base_signup_config(require_2fa_for_roles=["admin"])
    )
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)

    r = await client.get("/users/me/context")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "2fa_enrollment_required"

    # Add a confirmed TOTP row directly — we don't need to drive the
    # full enrollment ceremony to prove the gate releases.
    from datetime import UTC, datetime

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(
            UserTOTP(
                user_id=owner.id,
                secret="JBSWY3DPEHPK3PXP",
                confirmed_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await s.commit()

    r = await client.get("/users/me/context")
    assert r.status_code == 200, r.text
    assert r.json()["email"] == owner.email


@pytest.mark.asyncio
async def test_2fa_enforcement_off_when_role_not_listed(client, engine):
    """Default ``require_2fa_for_roles=[]`` lets an admin with no 2FA
    factor reach domain endpoints (the conftest ``_auto_pass_2fa``
    fixture marks the session full-access; the absence of an
    enforcement role means the second gate doesn't fire)."""
    await _wipe_auth_config(engine)
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)

    r = await client.get("/users/me/context")
    assert r.status_code == 200, r.text


@pytest.mark.real_2fa
@pytest.mark.asyncio
async def test_login_grants_full_session_when_unenforced(client, engine):
    """The strategy itself should write ``totp_passed=True`` when the
    user has no factor and no role on the enforcement list — without
    any test-helper bypass. Without this, the frontend still routes
    fresh logins to /2fa, which is the bug the AuthAdmin tab promises
    to fix.

    Marked ``real_2fa`` to bypass the conftest ``_auto_pass_2fa``
    patch; we explicitly wipe the auth namespace too so the enforce
    fixture's pre-write doesn't dirty the namespace.
    """
    from sqlalchemy import select as _select

    from app.models.auth_session import AuthSession

    await _wipe_auth_config(engine)
    owner = await seed_admin(engine)

    r = await client.post(
        "/auth/jwt/login",
        data={"username": owner.email, "password": "admin-pw-123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code in (200, 204), r.text

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        row = (
            await s.execute(
                _select(AuthSession).where(
                    AuthSession.user_id == owner.id,
                    AuthSession.revoked_at.is_(None),
                )
            )
        ).scalar_one()
    assert row.totp_passed is True, (
        "fresh login with no factor and empty require_2fa_for_roles "
        "must grant a full session — opt-in 2FA contract"
    )

    r = await client.get("/users/me/context")
    assert r.status_code == 200, r.text


@pytest.mark.real_2fa
@pytest.mark.asyncio
async def test_login_stays_partial_when_enforced(client, engine):
    """Mirror of the above: with ``require_2fa_for_roles`` covering the
    user's role, the strategy must hold the session partial so the
    frontend bounces them to /2fa for enrolment."""
    from sqlalchemy import select as _select

    from app.models.auth_session import AuthSession

    await _set_auth_config(
        engine, _base_signup_config(require_2fa_for_roles=["admin"])
    )
    owner = await seed_admin(engine)

    r = await client.post(
        "/auth/jwt/login",
        data={"username": owner.email, "password": "admin-pw-123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code in (200, 204), r.text

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        row = (
            await s.execute(
                _select(AuthSession).where(
                    AuthSession.user_id == owner.id,
                    AuthSession.revoked_at.is_(None),
                )
            )
        ).scalar_one()
    assert row.totp_passed is False, (
        "enforced role + no factor must keep the session partial "
        "until enrolment"
    )

    r = await client.get("/users/me/context")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "2fa_enrollment_required"
