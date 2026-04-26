"""WebAuthn second-factor: register / authenticate / list / delete flows.

The browser ceremony (``navigator.credentials.create`` / ``get``) can't
run inside pytest, so we stub ``verify_registration_response`` and
``verify_authentication_response`` at the router import site. Everything
else — challenge storage + purpose scoping, session promotion, credential
bookkeeping, the "last method" delete refusal — is real.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.email_otp import UserEmailOTP
from app.models.user_totp import UserTOTP
from app.models.webauthn import WebAuthnChallenge, WebAuthnCredential
from tests.helpers import login, login_partial, seed_admin

# WebAuthn register/finish promotes partial→full exactly like TOTP and
# email-OTP do; we need the real gate to observe the flip.
pytestmark = pytest.mark.real_2fa


# ------------------------------------------------------------------
# Fake verifier results — shape matches py_webauthn's dataclasses, but
# we only touch the fields the router reads.
# ------------------------------------------------------------------

@dataclass
class _FakeVerifiedRegistration:
    credential_id: bytes
    credential_public_key: bytes
    sign_count: int


@dataclass
class _FakeVerifiedAuthentication:
    new_sign_count: int


def _stub_verifiers(monkeypatch, *, credential_id: bytes = b"\x01\x02\x03\x04"):
    """Patch the verifier calls on the router module so any shaped
    payload passes. Returns the credential_id bytes so tests can echo
    them back in an assertion if needed."""
    from app.api import webauthn as router

    monkeypatch.setattr(
        router,
        "verify_registration_response",
        lambda **_: _FakeVerifiedRegistration(
            credential_id=credential_id,
            credential_public_key=b"\xAA" * 32,
            sign_count=0,
        ),
    )
    monkeypatch.setattr(
        router,
        "verify_authentication_response",
        lambda **_: _FakeVerifiedAuthentication(new_sign_count=1),
    )
    return credential_id


def _b64url_str(b: bytes) -> str:
    from base64 import urlsafe_b64encode

    return urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


async def _register_one(
    client,
    engine,
    monkeypatch,
    *,
    label: str = "YubiKey 5",
    credential_id: bytes = b"\x01\x02\x03\x04",
) -> WebAuthnCredential:
    """Drive a full begin+finish. Returns the persisted credential row."""
    cid = _stub_verifiers(monkeypatch, credential_id=credential_id)

    r = await client.post("/auth/webauthn/register/begin")
    assert r.status_code == 200, r.text

    payload = {
        "label": label,
        "credential": {
            "id": _b64url_str(cid),
            "rawId": _b64url_str(cid),
            "type": "public-key",
            "response": {
                "clientDataJSON": "fake",
                "attestationObject": "fake",
                "transports": ["usb"],
            },
            "clientExtensionResults": {},
        },
    }
    r = await client.post("/auth/webauthn/register/finish", json=payload)
    assert r.status_code == 204, r.text

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        cred = (
            await s.execute(
                select(WebAuthnCredential).where(
                    WebAuthnCredential.credential_id == _b64url_str(cid),
                )
            )
        ).scalar_one()
        return cred


# --- state endpoint --------------------------------------------------

@pytest.mark.asyncio
async def test_state_includes_webauthn_count(client, engine, monkeypatch):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)

    r = await client.get("/auth/totp/state")
    assert r.status_code == 200
    assert r.json()["webauthn_credential_count"] == 0

    await _register_one(client, engine, monkeypatch, label="Primary")

    r = await client.get("/auth/totp/state")
    assert r.json()["webauthn_credential_count"] == 1


# --- register begin + finish -----------------------------------------

@pytest.mark.asyncio
async def test_register_begin_stores_challenge_and_returns_options(
    client, engine, monkeypatch
):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)

    r = await client.post("/auth/webauthn/register/begin")
    assert r.status_code == 200
    options = r.json()["options"]
    # The browser needs these back; if they disappear the frontend
    # ceremony won't run.
    assert "challenge" in options
    assert options["rp"]["id"]  # server's RP id
    assert options["user"]["id"]  # base64url of the user's numeric id

    # Challenge row exists, scoped to register purpose.
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        rows = (
            await s.execute(
                select(WebAuthnChallenge).where(
                    WebAuthnChallenge.user_id == owner.id,
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].purpose == "register"


@pytest.mark.asyncio
async def test_register_begin_replaces_existing_challenge(
    client, engine, monkeypatch
):
    """Double-firing begin shouldn't leave orphan challenge rows."""
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)

    await client.post("/auth/webauthn/register/begin")
    await client.post("/auth/webauthn/register/begin")

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        rows = (
            await s.execute(
                select(WebAuthnChallenge).where(
                    WebAuthnChallenge.user_id == owner.id,
                    WebAuthnChallenge.purpose == "register",
                )
            )
        ).scalars().all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_register_finish_persists_credential_and_promotes(
    client, engine, monkeypatch
):
    # Force the partial-session path: with opt-in 2FA, a fresh admin
    # login otherwise grants ``totp_passed=True`` because no enforce
    # role is configured. Set enforcement explicitly so the webauthn
    # finish call has something to promote.
    from sqlalchemy.dialects.mysql import insert as mysql_insert

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

    # Pre-promote check: gate is still down.
    r = await client.get("/users/me/context")
    assert r.status_code == 403

    cred = await _register_one(client, engine, monkeypatch, label="YubiKey 5")
    assert cred.user_id == owner.id
    assert cred.label == "YubiKey 5"
    assert cred.transports == "usb"
    assert cred.sign_count == 0

    # Session was promoted to full by the finish call.
    r = await client.get("/auth/totp/state")
    assert r.json()["session_passed"] is True

    # Challenge row has been consumed.
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        rows = (
            await s.execute(
                select(WebAuthnChallenge).where(
                    WebAuthnChallenge.user_id == owner.id,
                    WebAuthnChallenge.purpose == "register",
                )
            )
        ).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_register_finish_without_begin_is_rejected(
    client, engine, monkeypatch
):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)
    _stub_verifiers(monkeypatch)

    payload = {
        "label": "Rogue",
        "credential": {
            "id": "AQID",
            "rawId": "AQID",
            "type": "public-key",
            "response": {
                "clientDataJSON": "x",
                "attestationObject": "x",
            },
            "clientExtensionResults": {},
        },
    }
    r = await client.post("/auth/webauthn/register/finish", json=payload)
    assert r.status_code == 400


# --- authenticate begin + finish ------------------------------------

@pytest.mark.asyncio
async def test_authenticate_flow_promotes_partial_to_full(
    client, engine, monkeypatch
):
    owner = await seed_admin(engine)
    # Register while partial — first-time 2FA promotes.
    await login_partial(client, owner.email, "admin-pw-123")
    await _register_one(client, engine, monkeypatch)

    # Fresh login → session is partial again.
    await client.post("/auth/jwt/logout")
    client.cookies.clear()
    await login_partial(client, owner.email, "admin-pw-123")
    r = await client.get("/auth/totp/state")
    assert r.json()["session_passed"] is False

    # Authenticate ceremony.
    _stub_verifiers(monkeypatch)
    r = await client.post("/auth/webauthn/authenticate/begin")
    assert r.status_code == 200
    options = r.json()["options"]
    assert options["allowCredentials"]  # the user's registered key

    raw_id = options["allowCredentials"][0]["id"]
    r = await client.post(
        "/auth/webauthn/authenticate/finish",
        json={
            "credential": {
                "id": raw_id,
                "rawId": raw_id,
                "type": "public-key",
                "response": {
                    "clientDataJSON": "x",
                    "authenticatorData": "x",
                    "signature": "x",
                    "userHandle": None,
                },
                "clientExtensionResults": {},
            }
        },
    )
    assert r.status_code == 204

    r = await client.get("/auth/totp/state")
    assert r.json()["session_passed"] is True

    # sign_count bumped, last_used_at set.
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        cred = (
            await s.execute(
                select(WebAuthnCredential).where(
                    WebAuthnCredential.user_id == owner.id,
                )
            )
        ).scalar_one()
        assert cred.sign_count == 1
        assert cred.last_used_at is not None


@pytest.mark.asyncio
async def test_authenticate_begin_rejects_when_no_credentials(
    client, engine, monkeypatch
):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)

    r = await client.post("/auth/webauthn/authenticate/begin")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_authenticate_finish_without_begin_is_rejected(
    client, engine, monkeypatch
):
    owner = await seed_admin(engine)
    await login_partial(client, owner.email, "admin-pw-123")
    await _register_one(client, engine, monkeypatch)
    _stub_verifiers(monkeypatch)

    # Skip begin → finish directly with a plausible payload.
    r = await client.post(
        "/auth/webauthn/authenticate/finish",
        json={
            "credential": {
                "id": _b64url_str(b"\x01\x02\x03\x04"),
                "rawId": _b64url_str(b"\x01\x02\x03\x04"),
                "type": "public-key",
                "response": {
                    "clientDataJSON": "x",
                    "authenticatorData": "x",
                    "signature": "x",
                },
                "clientExtensionResults": {},
            }
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_register_challenge_cant_finish_authenticate(
    client, engine, monkeypatch
):
    """Purpose scoping: a stored register challenge mustn't satisfy
    authenticate/finish (and vice versa)."""
    owner = await seed_admin(engine)
    await login_partial(client, owner.email, "admin-pw-123")
    cred = await _register_one(client, engine, monkeypatch)

    # Kick off a registration (stores a 'register' challenge)...
    await client.post("/auth/webauthn/register/begin")

    # ...then try to complete authenticate without its own begin.
    _stub_verifiers(monkeypatch)
    r = await client.post(
        "/auth/webauthn/authenticate/finish",
        json={
            "credential": {
                "id": cred.credential_id,
                "rawId": cred.credential_id,
                "type": "public-key",
                "response": {
                    "clientDataJSON": "x",
                    "authenticatorData": "x",
                    "signature": "x",
                },
                "clientExtensionResults": {},
            }
        },
    )
    assert r.status_code == 400


# --- list + delete ---------------------------------------------------

@pytest.mark.asyncio
async def test_list_credentials_returns_registered_set(
    client, engine, monkeypatch
):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)

    await _register_one(
        client, engine, monkeypatch,
        label="Primary", credential_id=b"\x01" * 8,
    )
    await _register_one(
        client, engine, monkeypatch,
        label="Backup", credential_id=b"\x02" * 8,
    )

    r = await client.get("/auth/webauthn/credentials")
    assert r.status_code == 200
    labels = sorted(row["label"] for row in r.json())
    assert labels == ["Backup", "Primary"]


@pytest.mark.asyncio
async def test_delete_refuses_if_last_2fa_method(
    client, engine, monkeypatch
):
    owner = await seed_admin(engine)
    await login_partial(client, owner.email, "admin-pw-123")
    cred = await _register_one(client, engine, monkeypatch)

    r = await client.delete(f"/auth/webauthn/credentials/{cred.id}")
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_delete_ok_when_totp_covers_2fa(client, engine, monkeypatch):
    owner = await seed_admin(engine)
    await login_partial(client, owner.email, "admin-pw-123")
    cred = await _register_one(client, engine, monkeypatch)

    # Now TOTP is also confirmed — removing the key is fine.
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

    r = await client.delete(f"/auth/webauthn/credentials/{cred.id}")
    assert r.status_code == 204

    async with factory() as s:
        rows = (
            await s.execute(
                select(WebAuthnCredential).where(
                    WebAuthnCredential.user_id == owner.id,
                )
            )
        ).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_delete_ok_when_other_webauthn_cred_exists(
    client, engine, monkeypatch
):
    """Two keys registered — removing one is fine; the other still
    covers 2FA."""
    owner = await seed_admin(engine)
    await login_partial(client, owner.email, "admin-pw-123")
    primary = await _register_one(
        client, engine, monkeypatch,
        label="Primary", credential_id=b"\x01" * 8,
    )
    await _register_one(
        client, engine, monkeypatch,
        label="Backup", credential_id=b"\x02" * 8,
    )

    r = await client.delete(f"/auth/webauthn/credentials/{primary.id}")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_delete_ok_when_email_otp_covers_2fa(
    client, engine, monkeypatch
):
    owner = await seed_admin(engine)
    await login_partial(client, owner.email, "admin-pw-123")
    cred = await _register_one(client, engine, monkeypatch)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(UserEmailOTP(user_id=owner.id, confirmed_at=datetime.utcnow()))
        await s.commit()

    r = await client.delete(f"/auth/webauthn/credentials/{cred.id}")
    assert r.status_code == 204


# --- admin reset wipes webauthn too ----------------------------------

@pytest.mark.asyncio
async def test_admin_reset_removes_webauthn_credentials(
    client, engine, monkeypatch
):
    from tests.helpers import login_fully_authenticated, seed_super_admin

    admin = await seed_super_admin(engine)
    target = await seed_admin(engine, email="target@example.com")

    # Drop a webauthn row directly on the target — avoids driving the
    # whole begin+finish dance with a separate cookie jar.
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(
            WebAuthnCredential(
                user_id=target.id,
                credential_id="ZmFrZQ",
                public_key=b"\xAA" * 32,
                sign_count=0,
                label="Target key",
            )
        )
        await s.commit()

    await login_fully_authenticated(client, engine, admin.email, "super-pw-123")
    r = await client.post(f"/admin/users/{target.id}/totp/reset")
    assert r.status_code == 204

    async with factory() as s:
        rows = (
            await s.execute(
                select(WebAuthnCredential).where(
                    WebAuthnCredential.user_id == target.id,
                )
            )
        ).scalars().all()
        assert rows == []
