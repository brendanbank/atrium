# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Coverage for the self-serve signup + email verification flow.

Pinned behaviours:

* ``auth.allow_signup=False`` makes ``POST /auth/register`` 404 — the
  route's existence is hidden when the operator hasn't opted in.
* The happy path creates a User, a verification row, an email_log
  row, and assigns the configured default RBAC role.
* Duplicate email returns 409 without creating a second row.
* ``POST /auth/verify-email`` flips ``users.email_verified_at``.
* Expired or already-consumed tokens return 400.
* ``auth.require_email_verification=True`` blocks login until the
  verification link has been clicked; flipping the toggle off lets
  unverified users in.
* The default role assigned to fresh signups is taken from
  ``auth.signup_default_role_code``.
* The public ``/app-config`` carve-out exposes the signup toggle.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.auth import User
from app.models.email_verification import EmailVerification
from app.models.ops import AppSetting, EmailLog
from app.models.rbac import Role, user_roles


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


async def _enable_signup(
    engine,
    *,
    require_email_verification: bool = True,
    signup_default_role_code: str = "user",
) -> None:
    await _set_auth_config(
        engine,
        {
            "allow_self_delete": True,
            "delete_grace_days": 30,
            "allow_signup": True,
            "signup_default_role_code": signup_default_role_code,
            "require_email_verification": require_email_verification,
        },
    )


async def _get_user_by_email(engine, email: str) -> User | None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        return (
            await s.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()


async def _get_verification_for_user(engine, user_id: int) -> EmailVerification:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        return (
            await s.execute(
                select(EmailVerification).where(
                    EmailVerification.user_id == user_id
                )
            )
        ).scalar_one()


async def _user_role_codes(engine, user_id: int) -> set[str]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        rows = (
            await s.execute(
                select(Role.code)
                .join(user_roles, user_roles.c.role_id == Role.id)
                .where(user_roles.c.user_id == user_id)
            )
        ).scalars().all()
    return set(rows)


@pytest.mark.asyncio
async def test_signup_disabled_returns_404(client, engine):
    """Default config has ``allow_signup=False`` — the route should
    look as if it doesn't exist."""
    await _wipe_auth_config(engine)
    r = await client.post(
        "/auth/register",
        json={
            "email": "newbie@example.com",
            "password": "fresh-pw-12345",
            "full_name": "Newbie",
        },
    )
    assert r.status_code == 404
    assert await _get_user_by_email(engine, "newbie@example.com") is None


@pytest.mark.asyncio
async def test_signup_happy_path(client, engine):
    await _enable_signup(engine)
    r = await client.post(
        "/auth/register",
        json={
            "email": "happy@example.com",
            "password": "fresh-pw-12345",
            "full_name": "Happy User",
            "language": "en",
        },
    )
    assert r.status_code == 204, r.text
    assert r.headers.get("Cache-Control") == "no-store"

    user = await _get_user_by_email(engine, "happy@example.com")
    assert user is not None
    assert user.is_active is True
    assert user.is_verified is False
    assert user.email_verified_at is None
    # Password was hashed (bcrypt / argon2 prefix).
    assert user.hashed_password.startswith(("$argon2", "$2b$", "$2a$"))

    # Default role assigned (``user`` per the toggle).
    assert await _user_role_codes(engine, user.id) == {"user"}

    # A verification row exists with a 64-char sha256 digest.
    verification = await _get_verification_for_user(engine, user.id)
    assert len(verification.token_sha256) == 64
    assert verification.consumed_at is None
    assert verification.expires_at > datetime.now(UTC).replace(tzinfo=None)

    # Email was logged.
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        log_rows = (
            await s.execute(
                select(EmailLog).where(EmailLog.template == "email_verify")
            )
        ).scalars().all()
    assert len(log_rows) == 1
    assert log_rows[0].to_addr == "happy@example.com"


@pytest.mark.asyncio
async def test_signup_duplicate_email_returns_409(client, engine):
    await _enable_signup(engine)
    payload = {
        "email": "dup@example.com",
        "password": "fresh-pw-12345",
        "full_name": "First",
    }
    r1 = await client.post("/auth/register", json=payload)
    assert r1.status_code == 204

    r2 = await client.post("/auth/register", json=payload)
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_verify_email_flips_email_verified_at(client, engine):
    """Drive the full register → verify flow end-to-end and assert the
    user row is marked verified."""
    await _enable_signup(engine)
    r = await client.post(
        "/auth/register",
        json={
            "email": "verify@example.com",
            "password": "fresh-pw-12345",
            "full_name": "V",
        },
    )
    assert r.status_code == 204
    user = await _get_user_by_email(engine, "verify@example.com")
    assert user is not None

    # We can't read the raw token (it's only sent in the email), so
    # generate a fresh token row directly and consume that. This
    # exercises the same consume_verification path the API hits.
    import hashlib
    import secrets

    raw = secrets.token_urlsafe(32)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        # Replace the auto-issued verification with one we know the
        # token for.
        await s.execute(
            delete(EmailVerification).where(
                EmailVerification.user_id == user.id
            )
        )
        s.add(
            EmailVerification(
                user_id=user.id,
                token_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                expires_at=datetime.now(UTC).replace(tzinfo=None)
                + timedelta(hours=1),
            )
        )
        await s.commit()

    r = await client.post("/auth/verify-email", json={"token": raw})
    assert r.status_code == 204, r.text

    refreshed = await _get_user_by_email(engine, "verify@example.com")
    assert refreshed is not None
    assert refreshed.email_verified_at is not None
    assert refreshed.is_verified is True


@pytest.mark.asyncio
async def test_verify_email_expired_token_returns_400(client, engine):
    await _enable_signup(engine)
    user = User(
        email="expired-tok@example.com",
        hashed_password="$2b$12$placeholderhashplaceholderhashplaceholderhash",
        is_active=True,
        is_verified=False,
        full_name="X",
        preferred_language="en",
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    import hashlib
    import secrets

    raw = secrets.token_urlsafe(32)
    async with factory() as s:
        s.add(user)
        await s.flush()
        s.add(
            EmailVerification(
                user_id=user.id,
                token_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                expires_at=datetime.now(UTC).replace(tzinfo=None)
                - timedelta(hours=1),
            )
        )
        await s.commit()

    r = await client.post("/auth/verify-email", json={"token": raw})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_verify_email_consumed_token_returns_400(client, engine):
    """A token that's already been used returns 400 on the second hit."""
    await _enable_signup(engine)
    import hashlib
    import secrets

    raw = secrets.token_urlsafe(32)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        u = User(
            email="consumed@example.com",
            hashed_password="$2b$12$placeholderhashplaceholderhashplaceholderhash",
            is_active=True,
            is_verified=False,
            full_name="C",
            preferred_language="en",
        )
        s.add(u)
        await s.flush()
        s.add(
            EmailVerification(
                user_id=u.id,
                token_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                expires_at=datetime.now(UTC).replace(tzinfo=None)
                + timedelta(hours=1),
            )
        )
        await s.commit()

    r1 = await client.post("/auth/verify-email", json={"token": raw})
    assert r1.status_code == 204
    r2 = await client.post("/auth/verify-email", json={"token": raw})
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_login_refused_when_unverified(client, engine):
    """With ``require_email_verification=True`` and no verification
    on the user row, login returns 400 (matching the bad-credentials
    surface so an attacker can't probe for verification state)."""
    await _enable_signup(engine, require_email_verification=True)
    r = await client.post(
        "/auth/register",
        json={
            "email": "unverified@example.com",
            "password": "fresh-pw-12345",
            "full_name": "U",
        },
    )
    assert r.status_code == 204

    login = await client.post(
        "/auth/jwt/login",
        data={"username": "unverified@example.com", "password": "fresh-pw-12345"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login.status_code in (400, 401)


@pytest.mark.asyncio
async def test_login_allowed_when_verification_disabled(client, engine):
    """Flipping ``require_email_verification=False`` lets the
    just-registered user log in immediately."""
    await _enable_signup(engine, require_email_verification=False)
    r = await client.post(
        "/auth/register",
        json={
            "email": "open@example.com",
            "password": "fresh-pw-12345",
            "full_name": "O",
        },
    )
    assert r.status_code == 204

    login = await client.post(
        "/auth/jwt/login",
        data={"username": "open@example.com", "password": "fresh-pw-12345"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login.status_code in (200, 204), login.text


@pytest.mark.asyncio
async def test_default_role_assignment_uses_config(client, engine):
    """Setting ``signup_default_role_code=admin`` makes fresh signups
    land in the admin role. Catches a regression where the service
    hardcodes ``user``."""
    await _enable_signup(engine, signup_default_role_code="admin")
    r = await client.post(
        "/auth/register",
        json={
            "email": "default-role@example.com",
            "password": "fresh-pw-12345",
            "full_name": "DR",
        },
    )
    assert r.status_code == 204
    user = await _get_user_by_email(engine, "default-role@example.com")
    assert user is not None
    assert await _user_role_codes(engine, user.id) == {"admin"}


@pytest.mark.asyncio
async def test_public_appconfig_exposes_signup_toggle(client, engine):
    """The carve-out in ``get_public_config`` surfaces just
    ``allow_signup`` so the LoginPage can gate the sign-up link
    without exposing the full AuthConfig."""
    await _enable_signup(engine, require_email_verification=True)
    r = await client.get("/app-config")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "auth" in body
    # ``allow_signup`` is the bit this test cares about. The bundle
    # also exposes captcha_provider + captcha_site_key (Phase 4) so
    # the widget can render — those are inherently public.
    assert body["auth"]["allow_signup"] is True
    # The full AuthConfig must NOT leak — no password policy, no
    # delete_grace_days, etc.
    assert "delete_grace_days" not in body["auth"]
    assert "require_email_verification" not in body["auth"]
    assert "captcha_secret" not in body["auth"]
