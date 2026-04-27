# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""TOTP enrollment + challenge + admin reset.

Covers the two-phase login contract:
- partial session blocks domain endpoints
- setup → confirm flips the current session to full-access
- verify does the same for returning users
- admin reset wipes the row and revokes active sessions
"""
from __future__ import annotations

import pyotp
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.auth_session import AuthSession
from app.models.user_totp import UserTOTP
from tests.helpers import (
    login,
    login_fully_authenticated,
    login_partial,
    seed_admin,
    seed_super_admin,
    seed_user,
)

# All tests in this module drive the real 2FA gate — conftest's
# ``_auto_pass_2fa`` fixture bypasses it by default and this marker
# opts back in.
pytestmark = pytest.mark.real_2fa


async def _get_totp_secret(engine, user_id: int) -> str:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        row = (
            await s.execute(select(UserTOTP).where(UserTOTP.user_id == user_id))
        ).scalar_one()
        return row.secret


async def _session_passed(engine, user_id: int) -> bool:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        row = (
            await s.execute(
                select(AuthSession)
                .where(
                    AuthSession.user_id == user_id,
                    AuthSession.revoked_at.is_(None),
                )
                .order_by(AuthSession.issued_at.desc())
            )
        ).scalar_one()
        return row.totp_passed


@pytest.mark.asyncio
async def test_fresh_user_login_lands_on_partial_session(client, engine):
    """When ``auth.require_2fa_for_roles`` includes the user's role,
    fresh login lands on a partial session — the user has no factor
    yet, so they're held at /2fa with ``2fa_enrollment_required`` until
    they enrol.

    With opt-in 2FA gating, a fresh login otherwise grants
    ``totp_passed=True`` for users with no factor and no enforced role.
    Set enforcement explicitly here so the partial-session path fires
    for the seeded admin.
    """
    from sqlalchemy.dialects.mysql import insert as mysql_insert
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.models.ops import AppSetting

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        stmt = mysql_insert(AppSetting).values(
            key="auth", value={"require_2fa_for_roles": ["admin"]}
        )
        stmt = stmt.on_duplicate_key_update(value=stmt.inserted.value)
        await s.execute(stmt)
        await s.commit()

    owner = await seed_admin(engine)
    await login_partial(client, owner.email, "admin-pw-123")

    # Domain endpoint is gated.
    r = await client.get("/users/me/context")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "2fa_enrollment_required"

    # ``/auth/totp/state`` is partial-auth; it reports session_passed=False.
    r = await client.get("/auth/totp/state")
    assert r.status_code == 200
    body = r.json()
    assert body["enrolled"] is False
    assert body["confirmed"] is False
    assert body["session_passed"] is False


@pytest.mark.asyncio
async def test_setup_then_confirm_finishes_enrollment(client, engine):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)

    r = await client.post("/auth/totp/setup")
    assert r.status_code == 200
    body = r.json()
    assert body["secret"]
    assert body["provisioning_uri"].startswith("otpauth://totp/")

    # Correct code finishes enrollment.
    code = pyotp.TOTP(body["secret"]).now()
    r = await client.post("/auth/totp/confirm", json={"code": code})
    assert r.status_code == 204

    r = await client.get("/auth/totp/state")
    body = r.json()
    assert body["enrolled"] is True
    assert body["confirmed"] is True
    assert body["session_passed"] is True


@pytest.mark.asyncio
async def test_confirm_rejects_bad_code(client, engine):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)
    await client.post("/auth/totp/setup")

    r = await client.post("/auth/totp/confirm", json={"code": "000000"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_login_after_enrollment_is_partial_until_verify(client, engine):
    owner = await seed_admin(engine)

    # Enroll once.
    await login(client, owner.email, "admin-pw-123", engine=engine)
    r = await client.post("/auth/totp/setup")
    secret = r.json()["secret"]
    await client.post(
        "/auth/totp/confirm", json={"code": pyotp.TOTP(secret).now()}
    )
    # fastapi-users logout flips the session row; clear cookie jar too.
    await client.post("/auth/jwt/logout")
    client.cookies.clear()

    # Re-login — the new session starts partial.
    await login_partial(client, owner.email, "admin-pw-123")
    assert await _session_passed(engine, owner.id) is False

    # Protected route is gated.
    r = await client.get("/users/me/context")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "totp_required"

    # State endpoint still works (partial-allowed).
    r = await client.get("/auth/totp/state")
    assert r.json()["session_passed"] is False

    # A valid code flips it.
    r = await client.post(
        "/auth/totp/verify", json={"code": pyotp.TOTP(secret).now()}
    )
    assert r.status_code == 204
    assert await _session_passed(engine, owner.id) is True

    r = await client.get("/users/me/context")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_verify_rejects_bad_code(client, engine):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)
    r = await client.post("/auth/totp/setup")
    secret = r.json()["secret"]
    await client.post(
        "/auth/totp/confirm", json={"code": pyotp.TOTP(secret).now()}
    )
    await client.post("/auth/jwt/logout")
    client.cookies.clear()
    await login_partial(client, owner.email, "admin-pw-123")

    r = await client.post("/auth/totp/verify", json={"code": "000000"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_setup_refuses_after_confirmed(client, engine):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)
    r = await client.post("/auth/totp/setup")
    secret = r.json()["secret"]
    await client.post(
        "/auth/totp/confirm", json={"code": pyotp.TOTP(secret).now()}
    )

    r = await client.post("/auth/totp/setup")
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_admin_reset_clears_enrollment_and_revokes_sessions(client, engine):
    admin = await seed_super_admin(engine)
    agent_obj = await seed_user(engine)
    # Give the agent a confirmed TOTP.
    await login(client, "user@example.com", "user-pw-123", engine=engine)
    r = await client.post("/auth/totp/setup")
    secret = r.json()["secret"]
    await client.post(
        "/auth/totp/confirm", json={"code": pyotp.TOTP(secret).now()}
    )
    await client.post("/auth/jwt/logout")
    client.cookies.clear()

    # Admin resets.
    await login_fully_authenticated(client, engine, admin.email, "super-pw-123")
    agent_user_id = agent_obj.id
    r = await client.post(f"/admin/users/{agent_user_id}/totp/reset")
    assert r.status_code == 204

    # Agent's TOTP row is gone.
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        row = (
            await s.execute(
                select(UserTOTP).where(UserTOTP.user_id == agent_user_id)
            )
        ).scalar_one_or_none()
        assert row is None

        # All the agent's sessions were revoked.
        rows = (
            await s.execute(
                select(AuthSession).where(AuthSession.user_id == agent_user_id)
            )
        ).scalars().all()
        assert rows
        assert all(r.revoked_at is not None for r in rows)


@pytest.mark.asyncio
async def test_non_super_admin_cannot_reset(client, engine):
    # Owner has user.totp.reset too, but a plain agent does not.
    await seed_user(engine)
    owner = await seed_admin(engine, email="other-owner@example.com")

    # Use full-auth login so the 403 is unambiguously about the
    # missing permission, not the TOTP gate.
    await login_fully_authenticated(
        client, engine, "user@example.com", "user-pw-123"
    )
    r = await client.post(f"/admin/users/{owner.id}/totp/reset")
    assert r.status_code == 403
