# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Integration tests for admin token endpoints."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth.pat_format import generate_token
from app.auth.pat_hashing import hash_token
from app.models.auth_token import AuthToken
from app.models.ops import AppSetting, AuditLog
from tests.helpers import login, seed_admin, seed_super_admin, seed_user


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _enable_pats(engine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(AppSetting(key="pats", value={"enabled": True}))
        await s.commit()


async def _seed_token(engine, user_id, **kwargs) -> int:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    plain, prefix = generate_token()
    async with factory() as s:
        row = AuthToken(
            user_id=user_id,
            created_by_user_id=user_id,
            token_prefix=prefix,
            token_hash=hash_token(plain),
            created_at=_utcnow(),
            **{"name": "t", "scopes": ["audit.read"], **kwargs},
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return row.id


@pytest_asyncio.fixture
async def super_admin_logged_in(client, engine):
    await _enable_pats(engine)
    user = await seed_super_admin(engine, email="super@example.com")
    await login(client, "super@example.com", "super-pw-123", engine=engine)
    return user


async def test_admin_role_lacks_admin_read(client, engine):
    """Plain admin has every permission EXCEPT user.impersonate +
    auth.pats.admin_*. Admin list should refuse a plain admin."""
    await _enable_pats(engine)
    await seed_admin(engine, email="just-admin@example.com")
    await login(client, "just-admin@example.com", "admin-pw-123", engine=engine)
    r = await client.get("/admin/auth/tokens")
    assert r.status_code == 403


async def test_super_admin_lists_all(client, engine, super_admin_logged_in):
    other = await seed_admin(engine, email="other@example.com")
    await _seed_token(engine, other.id, name="theirs")
    await _seed_token(engine, super_admin_logged_in.id, name="mine")

    r = await client.get("/admin/auth/tokens")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert {item["name"] for item in body["items"]} == {"theirs", "mine"}
    # The admin view exposes the holder's identity columns.
    for item in body["items"]:
        assert "user_email" in item


async def test_admin_filter_by_user_id(client, engine, super_admin_logged_in):
    other = await seed_admin(engine, email="other@example.com")
    await _seed_token(engine, other.id, name="o1")
    await _seed_token(engine, other.id, name="o2")
    await _seed_token(engine, super_admin_logged_in.id, name="mine")

    r = await client.get(f"/admin/auth/tokens?user_id={other.id}")
    assert r.status_code == 200
    assert r.json()["total"] == 2


async def test_admin_filter_by_status_revoked(
    client, engine, super_admin_logged_in
):
    user = super_admin_logged_in
    await _seed_token(engine, user.id, name="active")
    await _seed_token(
        engine,
        user.id,
        name="revoked",
        revoked_at=_utcnow(),
        revoke_reason="x",
    )

    r = await client.get("/admin/auth/tokens?status=revoked")
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["status"] == "revoked"


async def test_admin_filter_expiring_soon(
    client, engine, super_admin_logged_in
):
    user = super_admin_logged_in
    await _seed_token(
        engine, user.id, name="far", expires_at=_utcnow() + timedelta(days=60)
    )
    await _seed_token(
        engine, user.id, name="soon", expires_at=_utcnow() + timedelta(days=3)
    )

    r = await client.get("/admin/auth/tokens?expiring_within_days=7")
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["name"] == "soon"


async def test_admin_revoke_requires_reason(
    client, engine, super_admin_logged_in
):
    other = await seed_admin(engine, email="other@example.com")
    token_id = await _seed_token(engine, other.id)

    # Empty body — pydantic refuses (reason min_length=1 missing).
    r = await client.delete(f"/admin/auth/tokens/{token_id}")
    assert r.status_code == 422

    r = await client.request(
        "DELETE",
        f"/admin/auth/tokens/{token_id}",
        json={"reason": "compromised"},
    )
    assert r.status_code == 204


async def test_admin_revoke_writes_audit_with_reason(
    client, engine, session, super_admin_logged_in
):
    other = await seed_admin(engine, email="other@example.com")
    token_id = await _seed_token(engine, other.id)
    await client.request(
        "DELETE",
        f"/admin/auth/tokens/{token_id}",
        json={"reason": "incident-2026-05-01"},
    )

    rows = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.entity == "auth_token",
                AuditLog.entity_id == token_id,
                AuditLog.action == "revoke",
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].diff["reason"] == "incident-2026-05-01"
    assert rows[0].diff["via"] == "admin"
    assert rows[0].token_id == token_id


async def test_admin_revoke_all(client, engine, session, super_admin_logged_in):
    other = await seed_user(engine, email="compromised@example.com")
    for i in range(3):
        await _seed_token(engine, other.id, name=f"t{i}")
    # One token already revoked — bulk revoke ignores it.
    await _seed_token(
        engine, other.id, name="already", revoked_at=_utcnow(), revoke_reason="x"
    )

    r = await client.post(
        "/admin/auth/tokens/revoke_all",
        json={"user_id": other.id, "reason": "account compromised"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["revoked_count"] == 3
    assert body["user_id"] == other.id

    # All four are now revoked.
    rows = (
        await session.execute(
            select(AuthToken).where(AuthToken.user_id == other.id)
        )
    ).scalars().all()
    assert all(r.revoked_at is not None for r in rows)


async def test_admin_revoke_all_404_unknown_user(
    client, super_admin_logged_in
):
    r = await client.post(
        "/admin/auth/tokens/revoke_all",
        json={"user_id": 999_999, "reason": "x"},
    )
    assert r.status_code == 404


async def test_admin_per_token_audit_view(
    client, engine, super_admin_logged_in
):
    other = await seed_admin(engine, email="other@example.com")
    token_id = await _seed_token(engine, other.id)

    # Generate a couple of audit rows by revoking + listing.
    await client.request(
        "DELETE",
        f"/admin/auth/tokens/{token_id}",
        json={"reason": "test"},
    )
    r = await client.get(f"/admin/auth/tokens/{token_id}/audit")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    assert all(item["token_id"] == token_id for item in body["items"])
    actions = {item["action"] for item in body["items"]}
    assert "revoke" in actions


async def test_pat_cannot_call_admin_revoke(client, engine):
    """Even a super_admin's PAT carrying admin_revoke is refused —
    cookie_auth_required keeps the issuance / revocation surface
    cookie-only."""
    await _enable_pats(engine)
    super_admin = await seed_super_admin(engine, email="super@example.com")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    plain, prefix = generate_token()
    async with factory() as s:
        s.add(AuthToken(
            user_id=super_admin.id, created_by_user_id=super_admin.id,
            name="pat", token_prefix=prefix, token_hash=hash_token(plain),
            scopes=["auth.pats.admin_revoke"], created_at=_utcnow(),
        ))
        await s.commit()

    other = await seed_admin(engine, email="other@example.com")
    target_token_id = await _seed_token(engine, other.id)
    r = await client.request(
        "DELETE",
        f"/admin/auth/tokens/{target_token_id}",
        headers={"Authorization": f"Bearer {plain}"},
        json={"reason": "via PAT"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "cookie_auth_required"
