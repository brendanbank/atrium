# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Email-OTP second-factor: setup / confirm / request / verify /
disable flows, plus the updated ``/auth/totp/state`` and admin reset.

Mirrors ``tests/api/test_totp.py`` in structure. The ConsoleMailBackend
keeps mail out of SMTP; we dig the emitted code out of the ``EmailLog``
table + the challenge row (hash) since the real delivery body isn't
captured in the test harness.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.email.backend import reset_mail_backend_for_tests
from app.models.auth_session import AuthSession
from app.models.email_otp import EmailOTPChallenge, UserEmailOTP
from app.models.ops import EmailLog
from app.models.user_totp import UserTOTP
from tests.helpers import (
    login,
    login_fully_authenticated,
    login_partial,
    seed_admin,
    seed_super_admin,
)

# This module exercises the real 2FA gate; conftest's
# ``_auto_pass_2fa`` bypass would mask the behaviours under test.
pytestmark = pytest.mark.real_2fa


@pytest.fixture(autouse=True)
def _console_backend(monkeypatch):
    """Force the console mail backend so nothing reaches SMTP."""
    monkeypatch.setenv("MAIL_BACKEND", "console")
    reset_mail_backend_for_tests()
    yield
    reset_mail_backend_for_tests()


async def _latest_code_hash(engine, user_id: int) -> str:
    """Return the code_hash of the newest *unused* challenge. Skipping
    used ones is important — MySQL DATETIME(0) rounds to whole
    seconds, so when a test creates two challenges in the same second
    the ORDER BY is ambiguous and can hand back the already-consumed
    one. Scoping to ``used_at IS NULL`` sidesteps that entirely."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        row = (
            await s.execute(
                select(EmailOTPChallenge)
                .where(
                    EmailOTPChallenge.user_id == user_id,
                    EmailOTPChallenge.used_at.is_(None),
                )
                .order_by(
                    EmailOTPChallenge.created_at.desc(),
                    EmailOTPChallenge.id.desc(),
                )
                .limit(1)
            )
        ).scalar_one()
        return row.code_hash


def _brute_force_code_for_hash(expected_hash: str) -> str:
    """Recover the 6-digit code from its sha256. The space is 10^6 so
    this is a millisecond operation — fine for tests, and keeps the
    test harness from having to intercept outgoing mail."""
    for i in range(1_000_000):
        code = f"{i:06d}"
        if hashlib.sha256(code.encode()).hexdigest() == expected_hash:
            return code
    raise AssertionError("no matching code for hash")


async def _code_for(engine, user_id: int) -> str:
    return _brute_force_code_for_hash(await _latest_code_hash(engine, user_id))


# --- state endpoint -------------------------------------------------------

@pytest.mark.asyncio
async def test_state_includes_email_otp_fields(client, engine):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)

    r = await client.get("/auth/totp/state")
    assert r.status_code == 200
    body = r.json()
    assert body["enrolled"] is False
    assert body["confirmed"] is False
    assert body["email_otp_enrolled"] is False
    assert body["email_otp_confirmed"] is False


# --- setup + confirm ------------------------------------------------------

@pytest.mark.asyncio
async def test_setup_emails_code_and_creates_row(client, engine):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)

    r = await client.post("/auth/email-otp/setup")
    assert r.status_code == 204

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        # Row exists, unconfirmed.
        row = (
            await s.execute(select(UserEmailOTP).where(UserEmailOTP.user_id == owner.id))
        ).scalar_one()
        assert row.confirmed_at is None
        # One challenge row, not-yet-used.
        challenges = (
            await s.execute(
                select(EmailOTPChallenge).where(
                    EmailOTPChallenge.user_id == owner.id
                )
            )
        ).scalars().all()
        assert len(challenges) == 1
        assert challenges[0].used_at is None
        # EmailLog row confirms send was logged against the user's own
        # address.
        logs = (
            await s.execute(
                select(EmailLog).where(EmailLog.template == "email_otp_code")
            )
        ).scalars().all()
        assert any(log.to_addr == owner.email for log in logs)


@pytest.mark.asyncio
async def test_setup_is_idempotent_under_concurrent_call(client, engine):
    """React StrictMode fires the setup twice in dev; the endpoint
    must swallow the duplicate rather than 500."""
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)

    r1 = await client.post("/auth/email-otp/setup")
    r2 = await client.post("/auth/email-otp/setup")
    assert r1.status_code == 204
    assert r2.status_code == 204


@pytest.mark.asyncio
async def test_setup_cooldown_suppresses_duplicate_sends(client, engine):
    """Two setup calls within the cooldown window must result in one
    challenge row + one EmailLog entry — mitigates autofill (1Password
    etc.) double-trigger."""
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)

    await client.post("/auth/email-otp/setup")
    await client.post("/auth/email-otp/setup")

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        challenges = (
            await s.execute(
                select(EmailOTPChallenge).where(
                    EmailOTPChallenge.user_id == owner.id
                )
            )
        ).scalars().all()
        assert len(challenges) == 1
        logs = (
            await s.execute(
                select(EmailLog).where(
                    EmailLog.template == "email_otp_code",
                    EmailLog.to_addr == owner.email,
                )
            )
        ).scalars().all()
        assert len(logs) == 1


@pytest.mark.asyncio
async def test_request_cooldown_suppresses_duplicate_sends(client, engine):
    """Same cooldown must protect /request, which is what the returning
    user hits on the challenge screen."""
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)
    await client.post("/auth/email-otp/setup")
    code = await _code_for(engine, owner.id)
    await client.post("/auth/email-otp/confirm", json={"code": code})
    await client.post("/auth/jwt/logout")
    client.cookies.clear()

    await login_partial(client, owner.email, "admin-pw-123")

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        before_logs = (
            await s.execute(
                select(EmailLog).where(EmailLog.template == "email_otp_code")
            )
        ).scalars().all()
    assert len(before_logs) == 1  # the confirm flow's own code

    await client.post("/auth/email-otp/request")
    await client.post("/auth/email-otp/request")

    async with factory() as s:
        after_logs = (
            await s.execute(
                select(EmailLog).where(EmailLog.template == "email_otp_code")
            )
        ).scalars().all()
    # One new send from the first /request; the second was within the
    # cooldown and returned 204 without emailing again.
    assert len(after_logs) == len(before_logs) + 1


@pytest.mark.asyncio
async def test_confirm_with_right_code_flips_session_full(client, engine):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)

    await client.post("/auth/email-otp/setup")
    code = await _code_for(engine, owner.id)
    r = await client.post("/auth/email-otp/confirm", json={"code": code})
    assert r.status_code == 204

    # State now reports confirmed + session promoted to full.
    r = await client.get("/auth/totp/state")
    body = r.json()
    assert body["email_otp_confirmed"] is True
    assert body["session_passed"] is True


@pytest.mark.asyncio
async def test_confirm_rejects_wrong_code(client, engine):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)
    await client.post("/auth/email-otp/setup")

    r = await client.post("/auth/email-otp/confirm", json={"code": "000000"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_confirm_rejects_expired_code(client, engine):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)
    await client.post("/auth/email-otp/setup")

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        challenge = (
            await s.execute(
                select(EmailOTPChallenge).where(
                    EmailOTPChallenge.user_id == owner.id
                )
            )
        ).scalar_one()
        challenge.expires_at = datetime.utcnow() - timedelta(minutes=1)
        await s.commit()

    code = await _code_for(engine, owner.id)
    r = await client.post("/auth/email-otp/confirm", json={"code": code})
    assert r.status_code == 400


# --- login challenge (verify) --------------------------------------------

@pytest.mark.asyncio
async def test_login_after_enrollment_is_partial_until_verify(client, engine):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)
    await client.post("/auth/email-otp/setup")
    code = await _code_for(engine, owner.id)
    await client.post("/auth/email-otp/confirm", json={"code": code})
    await client.post("/auth/jwt/logout")
    client.cookies.clear()

    # Re-login — session starts partial.
    await login_partial(client, owner.email, "admin-pw-123")
    r = await client.get("/auth/totp/state")
    body = r.json()
    assert body["session_passed"] is False

    # Protected route is gated.
    r = await client.get("/users/me/context")
    assert r.status_code == 403

    # Request a fresh code, verify.
    await client.post("/auth/email-otp/request")
    code = await _code_for(engine, owner.id)
    r = await client.post("/auth/email-otp/verify", json={"code": code})
    assert r.status_code == 204

    r = await client.get("/auth/totp/state")
    assert r.json()["session_passed"] is True


@pytest.mark.asyncio
async def test_request_refuses_when_not_enrolled(client, engine):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)
    r = await client.post("/auth/email-otp/request")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_verify_marks_code_used_so_replay_fails(client, engine):
    """After a successful verify, the same code can't be used to flip
    another session's totp_passed."""
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)
    await client.post("/auth/email-otp/setup")
    code = await _code_for(engine, owner.id)
    await client.post("/auth/email-otp/confirm", json={"code": code})
    await client.post("/auth/jwt/logout")
    client.cookies.clear()

    # Login #1: request + verify.
    await login_partial(client, owner.email, "admin-pw-123")
    await client.post("/auth/email-otp/request")
    code = await _code_for(engine, owner.id)
    r = await client.post("/auth/email-otp/verify", json={"code": code})
    assert r.status_code == 204

    # Login #2 (fresh cookie jar): same code must be rejected.
    await client.post("/auth/jwt/logout")
    client.cookies.clear()
    await login_partial(client, owner.email, "admin-pw-123")
    r = await client.post("/auth/email-otp/verify", json={"code": code})
    assert r.status_code == 400


# --- disable --------------------------------------------------------------

@pytest.mark.asyncio
async def test_disable_refuses_if_only_method(client, engine):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)
    await client.post("/auth/email-otp/setup")
    code = await _code_for(engine, owner.id)
    await client.post("/auth/email-otp/confirm", json={"code": code})

    r = await client.post("/auth/email-otp/disable")
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_disable_ok_when_other_method_active(client, engine):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)

    # Pretend TOTP is already confirmed — directly insert the row so
    # we don't have to drive the pyotp code dance here.
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(
            UserTOTP(
                user_id=owner.id,
                secret="A" * 32,
                confirmed_at=datetime.utcnow(),
            )
        )
        await s.commit()

    await client.post("/auth/email-otp/setup")
    code = await _code_for(engine, owner.id)
    await client.post("/auth/email-otp/confirm", json={"code": code})

    r = await client.post("/auth/email-otp/disable")
    assert r.status_code == 204

    # Row is gone.
    async with factory() as s:
        row = (
            await s.execute(
                select(UserEmailOTP).where(UserEmailOTP.user_id == owner.id)
            )
        ).scalar_one_or_none()
        assert row is None


@pytest.mark.asyncio
async def test_totp_disable_refuses_if_only_method(client, engine):
    """Symmetric check on the new ``/auth/totp/disable`` endpoint."""
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(
            UserTOTP(
                user_id=owner.id,
                secret="A" * 32,
                confirmed_at=datetime.utcnow(),
            )
        )
        await s.commit()

    r = await client.post("/auth/totp/disable")
    assert r.status_code == 409


# --- admin reset ---------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_reset_wipes_both_methods(client, engine):
    admin = await seed_super_admin(engine)
    target = await seed_admin(engine, email="target@example.com")

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(
            UserTOTP(
                user_id=target.id,
                secret="A" * 32,
                confirmed_at=datetime.utcnow(),
            )
        )
        s.add(UserEmailOTP(user_id=target.id, confirmed_at=datetime.utcnow()))
        await s.commit()

    await login_fully_authenticated(client, engine, admin.email, "super-pw-123")
    r = await client.post(f"/admin/users/{target.id}/totp/reset")
    assert r.status_code == 204

    async with factory() as s:
        totp = (
            await s.execute(select(UserTOTP).where(UserTOTP.user_id == target.id))
        ).scalar_one_or_none()
        email_otp = (
            await s.execute(
                select(UserEmailOTP).where(UserEmailOTP.user_id == target.id)
            )
        ).scalar_one_or_none()
        assert totp is None
        assert email_otp is None

        # Target's active sessions are revoked too.
        sessions = (
            await s.execute(
                select(AuthSession).where(AuthSession.user_id == target.id)
            )
        ).scalars().all()
        assert all(s_.revoked_at is not None for s_ in sessions)
