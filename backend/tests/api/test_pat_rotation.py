# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Rotate flow: old revoked, new active, audit linkage on both sides."""
from __future__ import annotations

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.auth_token import AuthToken
from app.models.ops import AppSetting, AuditLog
from tests.helpers import login, seed_admin


async def _enable_pats(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(AppSetting(key="pats", value={"enabled": True}))
        await s.commit()


@pytest_asyncio.fixture
async def admin_logged_in(client, engine):
    await _enable_pats(engine)
    user = await seed_admin(engine, email="rot@example.com")
    await login(client, "rot@example.com", "admin-pw-123", engine=engine)
    return user


async def test_rotate_returns_new_plaintext(client, admin_logged_in):
    r = await client.post(
        "/auth/tokens",
        json={"name": "to-rotate", "scopes": ["audit.read"], "expires_in_days": 30},
    )
    old_id = r.json()["id"]
    old_token = r.json()["token"]

    r = await client.post(f"/auth/tokens/{old_id}/rotate")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["token"].startswith("atr_pat_")
    assert body["token"] != old_token
    assert body["scopes"] == ["audit.read"]
    assert body["status"] == "active"


async def test_rotate_revokes_old_token(
    client, engine, session, admin_logged_in
):
    r = await client.post(
        "/auth/tokens", json={"name": "x", "scopes": ["audit.read"]}
    )
    old_id = r.json()["id"]

    await client.post(f"/auth/tokens/{old_id}/rotate")

    old = (
        await session.execute(
            select(AuthToken).where(AuthToken.id == old_id)
        )
    ).scalar_one()
    assert old.revoked_at is not None
    assert old.revoke_reason == "rotated"


async def test_rotate_audit_links_both_rows(
    client, engine, session, admin_logged_in
):
    r = await client.post(
        "/auth/tokens", json={"name": "x", "scopes": ["audit.read"]}
    )
    old_id = r.json()["id"]
    r = await client.post(f"/auth/tokens/{old_id}/rotate")
    new_id = r.json()["id"]

    rows = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.entity == "auth_token",
                AuditLog.action == "rotate",
            )
        )
    ).scalars().all()
    assert len(rows) == 2
    by_entity = {r.entity_id: r for r in rows}
    assert by_entity[new_id].diff["previous_token_id"] == old_id
    assert by_entity[old_id].diff["replaced_by_token_id"] == new_id


async def test_rotate_old_inert_for_auth(client, engine, admin_logged_in):
    """The old plaintext stops authenticating; the new one works."""
    r = await client.post(
        "/auth/tokens", json={"name": "x", "scopes": ["audit.read"]}
    )
    old_id = r.json()["id"]
    old_token = r.json()["token"]
    r = await client.post(f"/auth/tokens/{old_id}/rotate")
    new_token = r.json()["token"]

    # New works.
    r = await client.get(
        "/admin/audit", headers={"Authorization": f"Bearer {new_token}"}
    )
    assert r.status_code == 200, r.text
    # Old is rejected (revoked → invalid_token).
    r = await client.get(
        "/admin/audit", headers={"Authorization": f"Bearer {old_token}"}
    )
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_token"


async def test_rotate_404_for_revoked_token(client, admin_logged_in):
    r = await client.post(
        "/auth/tokens", json={"name": "x", "scopes": ["audit.read"]}
    )
    old_id = r.json()["id"]
    await client.delete(f"/auth/tokens/{old_id}")
    r = await client.post(f"/auth/tokens/{old_id}/rotate")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "token_revoked"
