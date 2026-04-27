# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Impersonation API — guardrails + round-trip.

Verifies that /admin/users/{id}/impersonate + /admin/impersonate/stop
swap the auth cookie as expected, that /users/me/context reflects the
swap, and that each hard-coded guard refuses the corresponding abuse.
"""
from __future__ import annotations

import pytest

from tests.helpers import login, seed_admin, seed_super_admin, seed_user


@pytest.mark.asyncio
async def test_super_admin_can_impersonate_agent_and_stop(client, engine):
    super_admin = await seed_super_admin(engine)
    agent = await seed_user(engine)
    await login(client, super_admin.email, "super-pw-123", engine=engine)

    agent_user_id = agent.id

    r = await client.post(f"/admin/users/{agent_user_id}/impersonate")
    assert r.status_code == 200, r.text
    assert r.json()["id"] == agent_user_id

    # Context now reflects the target with impersonating_from pointing
    # back at the super_admin.
    ctx = (await client.get("/users/me/context")).json()
    assert ctx["id"] == agent_user_id
    assert ctx["impersonating_from"]["id"] == super_admin.id
    # Target's permission set, not the super_admin's. Atrium's plain
    # ``user`` role has none, so the list should be empty.
    assert "user.impersonate" not in ctx["permissions"]
    assert ctx["permissions"] == []

    # Stop — context swings back.
    r = await client.post("/admin/impersonate/stop")
    assert r.status_code == 200, r.text
    ctx = (await client.get("/users/me/context")).json()
    assert ctx["id"] == super_admin.id
    assert ctx["impersonating_from"] is None


@pytest.mark.asyncio
async def test_cannot_impersonate_self(client, engine):
    super_admin = await seed_super_admin(engine)
    await login(client, super_admin.email, "super-pw-123", engine=engine)
    r = await client.post(f"/admin/users/{super_admin.id}/impersonate")
    assert r.status_code == 400
    assert "yourself" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_cannot_impersonate_another_super_admin(client, engine):
    super_a = await seed_super_admin(engine, email="a@example.com")
    super_b = await seed_super_admin(engine, email="b@example.com")
    await login(client, super_a.email, "super-pw-123", engine=engine)

    r = await client.post(f"/admin/users/{super_b.id}/impersonate")
    assert r.status_code == 403
    # Key guardrail — prevents privilege-escalation loops.
    assert "super admin" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_cannot_impersonate_inactive_user(client, engine):
    super_admin = await seed_super_admin(engine)
    agent = await seed_user(engine)
    # Deactivate the target.
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.models.auth import User

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await s.execute(
            update(User).where(User.id == agent.id).values(is_active=False)
        )
        await s.commit()

    await login(client, super_admin.email, "super-pw-123", engine=engine)
    r = await client.post(f"/admin/users/{agent.id}/impersonate")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_plain_owner_cannot_impersonate(client, engine):
    # Owner without super_admin → doesn't hold user.impersonate.
    owner = await seed_admin(engine, email="plain-owner@example.com")
    agent = await seed_user(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)

    r = await client.post(f"/admin/users/{agent.id}/impersonate")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_stop_without_impersonator_cookie_errors(client, engine):
    owner = await seed_super_admin(engine)
    await login(client, owner.email, "super-pw-123", engine=engine)

    # No impersonation started → no cookie → 400.
    r = await client.post("/admin/impersonate/stop")
    assert r.status_code == 400


@pytest.mark.asyncio
@pytest.mark.real_2fa
async def test_impersonation_inherits_totp_passed_both_ways(client, engine):
    """Super-admin has already cleared 2FA; the minted target session
    and the restored actor session must both land as totp_passed=True
    so the user isn't bounced to /2fa twice per impersonation."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.models.auth_session import AuthSession
    from app.models.user_totp import UserTOTP

    # Seed super-admin with confirmed TOTP so the real_2fa gate is
    # enforceable; then login + manually flip totp_passed to simulate
    # having just cleared the challenge.
    super_admin = await seed_super_admin(engine)
    agent = await seed_user(engine)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    from datetime import datetime

    async with factory() as s:
        s.add(
            UserTOTP(
                user_id=super_admin.id,
                secret="A" * 32,
                confirmed_at=datetime.utcnow(),
            )
        )
        await s.commit()

    await login(client, super_admin.email, "super-pw-123", engine=engine)

    r = await client.post(f"/admin/users/{agent.id}/impersonate")
    assert r.status_code == 200, r.text
    # /users/me/context requires a *full* session — a partial one would
    # 403 with totp_required. A 200 proves the impersonated session
    # carries totp_passed=True.
    r = await client.get("/users/me/context")
    assert r.status_code == 200
    assert r.json()["id"] == agent.id

    # Stop — same check for the restored actor session.
    r = await client.post("/admin/impersonate/stop")
    assert r.status_code == 200
    r = await client.get("/users/me/context")
    assert r.status_code == 200
    assert r.json()["id"] == super_admin.id

    # Belt-and-braces: assert the two freshly-minted rows are flagged.
    async with factory() as s:
        rows = (
            await s.execute(
                select(AuthSession)
                .where(AuthSession.revoked_at.is_(None))
                .order_by(AuthSession.issued_at.desc())
                .limit(2)
            )
        ).scalars().all()
        assert len(rows) >= 2
        assert all(r.totp_passed for r in rows)
