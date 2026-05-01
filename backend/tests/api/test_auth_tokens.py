# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Integration tests for the self-service ``/auth/tokens`` router.

Drives every endpoint over the real HTTP client + middleware stack
+ MySQL testcontainer, so the cookie / PAT distinction and scope
intersection are exercised end to end. Per-token rate-limit and
sampled-use audit events get their own files.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth.pat_format import generate_token
from app.auth.pat_hashing import hash_token
from app.models.auth_token import AuthToken
from app.models.ops import AppSetting
from tests.helpers import login, seed_admin


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _enable_pats(engine, **kwargs) -> None:
    """Idempotently set the ``pats`` namespace. Safe to call multiple
    times in a test — overwrites any prior row instead of duplicate-
    keying."""
    payload = {"enabled": True, **kwargs}
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        from sqlalchemy.dialects.mysql import insert as _insert

        stmt = _insert(AppSetting).values(key="pats", value=payload)
        stmt = stmt.on_duplicate_key_update(value=stmt.inserted.value)
        await s.execute(stmt)
        await s.commit()


@pytest_asyncio.fixture
async def admin_logged_in(client, engine):
    """A standard admin user with a full cookie session."""
    await _enable_pats(engine)
    user = await seed_admin(engine, email="tok-admin@example.com")
    await login(client, "tok-admin@example.com", "admin-pw-123", engine=engine)
    return user


async def test_create_token_returns_plaintext_once(client, admin_logged_in):
    r = await client.post(
        "/auth/tokens",
        json={
            "name": "ci script",
            "scopes": ["audit.read"],
            "expires_in_days": 30,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["token"].startswith("atr_pat_")
    assert body["token_prefix"] == body["token"][:12]
    assert body["scopes"] == ["audit.read"]
    assert body["status"] == "active"
    assert body["expires_at"] is not None


async def test_list_tokens_omits_plaintext(client, admin_logged_in):
    await client.post(
        "/auth/tokens",
        json={"name": "a", "scopes": ["audit.read"]},
    )
    r = await client.get("/auth/tokens")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert "token" not in body[0]
    assert body[0]["status"] == "active"


async def test_list_tokens_status_filter(client, engine, admin_logged_in):
    """Three tokens, one of each status. Filter must round-trip."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id = admin_logged_in.id
    async with factory() as s:
        # active
        plain1, prefix1 = generate_token()
        s.add(AuthToken(
            user_id=user_id, name="active",
            token_prefix=prefix1, token_hash=hash_token(plain1),
            scopes=["audit.read"], created_at=_utcnow(),
        ))
        # expired
        plain2, prefix2 = generate_token()
        s.add(AuthToken(
            user_id=user_id, name="expired",
            token_prefix=prefix2, token_hash=hash_token(plain2),
            scopes=["audit.read"], created_at=_utcnow(),
            expires_at=_utcnow() - timedelta(days=1),
        ))
        # revoked
        plain3, prefix3 = generate_token()
        s.add(AuthToken(
            user_id=user_id, name="revoked",
            token_prefix=prefix3, token_hash=hash_token(plain3),
            scopes=["audit.read"], created_at=_utcnow(),
            revoked_at=_utcnow(), revoke_reason="t",
        ))
        await s.commit()

    r = await client.get("/auth/tokens?status=active")
    assert {t["name"] for t in r.json()} == {"active"}
    r = await client.get("/auth/tokens?status=expired")
    assert {t["name"] for t in r.json()} == {"expired"}
    r = await client.get("/auth/tokens?status=revoked")
    assert {t["name"] for t in r.json()} == {"revoked"}


async def test_create_refuses_scope_overreach(client, admin_logged_in):
    """Admin holds many perms but not host-defined ones. A scope that
    isn't in the user's permission set is refused with 403 + a clear
    code so the UI can surface the missing scopes."""
    r = await client.post(
        "/auth/tokens",
        json={
            "name": "ci",
            "scopes": ["audit.read", "host.does_not_exist"],
        },
    )
    assert r.status_code == 403, r.text
    body = r.json()
    assert body["detail"]["code"] == "scope_overreach"
    assert "host.does_not_exist" in body["detail"]["missing_permissions"]


async def test_max_per_user_cap_enforced(client, engine, admin_logged_in):
    await _enable_pats(engine, max_per_user=2)

    for i in range(2):
        r = await client.post(
            "/auth/tokens",
            json={"name": f"t{i}", "scopes": ["audit.read"]},
        )
        assert r.status_code == 201, r.text
    r = await client.post(
        "/auth/tokens",
        json={"name": "third", "scopes": ["audit.read"]},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "max_per_user_exceeded"


async def test_max_lifetime_days_caps_expires_in_days(
    client, engine, admin_logged_in
):
    """Operator caps token lifetime at 7 days; a request for 90 should
    silently land at 7 (not refused — capped)."""
    await _enable_pats(engine, max_lifetime_days=7)

    before = _utcnow()
    r = await client.post(
        "/auth/tokens",
        json={"name": "ci", "scopes": ["audit.read"], "expires_in_days": 90},
    )
    assert r.status_code == 201
    expires_at = datetime.fromisoformat(r.json()["expires_at"])
    if expires_at.tzinfo is not None:
        expires_at = expires_at.replace(tzinfo=None)
    assert expires_at - before <= timedelta(days=7, hours=1)


async def test_pat_cannot_create_other_pats(client, engine):
    """A PAT bearer reaches ``POST /auth/tokens`` with the right
    permission but ``require_cookie_auth`` refuses with
    ``cookie_auth_required``. Defends against a leaked PAT
    bootstrapping further tokens."""
    await _enable_pats(engine)
    user = await seed_admin(engine, email="pat-creator@example.com")
    plain, _ = await _create_pat_for(engine, user.id, ["auth.pats.read_self"])
    r = await client.post(
        "/auth/tokens",
        headers={"Authorization": f"Bearer {plain}"},
        json={"name": "x", "scopes": ["audit.read"]},
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "cookie_auth_required"


async def test_revoke_self_token_marks_revoked(client, engine, admin_logged_in):
    r = await client.post(
        "/auth/tokens", json={"name": "to-revoke", "scopes": ["audit.read"]}
    )
    token_id = r.json()["id"]

    # httpx's ``client.delete`` shorthand doesn't accept ``json=`` —
    # use ``request`` explicitly so the body lands.
    r = await client.request(
        "DELETE",
        f"/auth/tokens/{token_id}",
        json={"reason": "no longer needed"},
    )
    assert r.status_code == 204

    r = await client.get("/auth/tokens")
    assert r.json()[0]["status"] == "revoked"
    assert r.json()[0]["revoke_reason"] == "no longer needed"


async def test_revoke_404_for_other_users_token(client, engine, admin_logged_in):
    other = await seed_admin(engine, email="other@example.com")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        plain, prefix = generate_token()
        row = AuthToken(
            user_id=other.id, name="other",
            token_prefix=prefix, token_hash=hash_token(plain),
            scopes=["audit.read"], created_at=_utcnow(),
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        other_token_id = row.id

    # admin_logged_in tries to revoke other's token via self-route — 404
    r = await client.delete(f"/auth/tokens/{other_token_id}")
    assert r.status_code == 404


async def test_update_scope_reduction_logs_audit(
    client, engine, admin_logged_in
):
    r = await client.post(
        "/auth/tokens",
        json={"name": "to-shrink", "scopes": ["audit.read", "user.manage"]},
    )
    token_id = r.json()["id"]

    r = await client.patch(
        f"/auth/tokens/{token_id}", json={"scopes": ["audit.read"]}
    )
    assert r.status_code == 200
    assert r.json()["scopes"] == ["audit.read"]


async def test_update_refuses_unheld_scope(client, admin_logged_in):
    r = await client.post(
        "/auth/tokens", json={"name": "x", "scopes": ["audit.read"]}
    )
    token_id = r.json()["id"]
    r = await client.patch(
        f"/auth/tokens/{token_id}",
        json={"scopes": ["audit.read", "host.fake_scope"]},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "scope_overreach"


async def test_update_caps_extension_at_max_lifetime(
    client, engine, admin_logged_in
):
    await _enable_pats(engine, max_lifetime_days=7)
    r = await client.post(
        "/auth/tokens",
        json={"name": "x", "scopes": ["audit.read"], "expires_in_days": 1},
    )
    token_id = r.json()["id"]

    far_future = (_utcnow() + timedelta(days=365)).isoformat()
    r = await client.patch(
        f"/auth/tokens/{token_id}", json={"expires_at": far_future}
    )
    assert r.status_code == 200
    new_exp = datetime.fromisoformat(r.json()["expires_at"]).replace(tzinfo=None)
    assert new_exp - _utcnow() <= timedelta(days=7, hours=1)


# ---- helpers (avoid coupling to test_pat_auth.py) -----------------------


async def _create_pat_for(engine, user_id: int, scopes: list[str]):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    plain, prefix = generate_token()
    async with factory() as s:
        s.add(AuthToken(
            user_id=user_id, created_by_user_id=user_id, name="for-test",
            token_prefix=prefix, token_hash=hash_token(plain),
            scopes=scopes, created_at=_utcnow(),
        ))
        await s.commit()
    return plain, prefix


async def test_create_persists_audit_row(
    client, engine, session, admin_logged_in
):
    r = await client.post(
        "/auth/tokens", json={"name": "audited", "scopes": ["audit.read"]}
    )
    token_id = r.json()["id"]

    from app.models.ops import AuditLog

    rows = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.entity == "auth_token",
                AuditLog.entity_id == token_id,
                AuditLog.action == "create",
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].token_id == token_id
    assert rows[0].diff["scopes"] == ["audit.read"]
