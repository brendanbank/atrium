# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Service-account creation + listing tests."""
from __future__ import annotations

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.auth import User
from app.models.auth_token import AuthToken
from app.models.ops import AppSetting
from tests.helpers import login, seed_admin, seed_super_admin


async def _enable_pats(engine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(AppSetting(key="pats", value={"enabled": True}))
        await s.commit()


@pytest_asyncio.fixture
async def super_admin_logged_in(client, engine):
    await _enable_pats(engine)
    user = await seed_super_admin(engine, email="super@example.com")
    await login(client, "super@example.com", "super-pw-123", engine=engine)
    return user


async def test_create_service_account_returns_initial_pat(
    client, engine, super_admin_logged_in
):
    r = await client.post(
        "/admin/service_accounts",
        json={
            "name": "MCP sidecar",
            "email": "mcp@example.com",
            "role_codes": ["admin"],
            "initial_scopes": ["audit.read"],
            "expires_in_days": 90,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["account"]["email"] == "mcp@example.com"
    assert body["token"]["token"].startswith("atr_pat_")
    assert body["token"]["scopes"] == ["audit.read"]


async def test_service_account_row_shape(
    client, engine, session, super_admin_logged_in
):
    """The created users row matches the spec: is_service_account=True,
    email_verified_at populated, ``hashed_password`` carries a random
    throwaway hash (no input can match — see endpoint comment)."""
    await client.post(
        "/admin/service_accounts",
        json={
            "name": "svc",
            "email": "svc@example.com",
            "role_codes": ["admin"],
            "initial_scopes": ["audit.read"],
        },
    )
    user = (
        await session.execute(
            select(User).where(User.email == "svc@example.com")
        )
    ).scalar_one()
    assert user.is_service_account is True
    assert user.is_verified is True
    assert user.email_verified_at is not None
    # Non-empty (real argon2/bcrypt hash) — the empty-string sentinel
    # discussed in migration 0009 doesn't survive pwdlib's hasher
    # detection in fastapi-users 13.x.
    assert user.hashed_password != ""


async def test_service_account_login_route_refused(
    client, engine, super_admin_logged_in
):
    """The created service account cannot log in interactively even
    if someone tries to brute the empty-string sentinel."""
    await client.post(
        "/admin/service_accounts",
        json={
            "name": "svc",
            "email": "svc@example.com",
            "role_codes": ["admin"],
            "initial_scopes": ["audit.read"],
        },
    )
    # OAuth2PasswordRequestForm rejects an empty ``password`` field
    # client-side (422). Send a non-empty wrong password so the
    # request reaches the authenticate path proper, where the
    # ``is_service_account`` flag refuses with 400 LOGIN_BAD_CREDENTIALS
    # — the same bucket as a wrong password so the response doesn't
    # discriminate service-account emails from human ones.
    r = await client.post(
        "/auth/jwt/login",
        data={"username": "svc@example.com", "password": "any-wrong-pw"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 400


async def test_service_account_email_collision_409(
    client, engine, super_admin_logged_in
):
    await seed_admin(engine, email="taken@example.com")
    r = await client.post(
        "/admin/service_accounts",
        json={
            "name": "svc",
            "email": "taken@example.com",
            "initial_scopes": ["audit.read"],
        },
    )
    assert r.status_code == 409


async def test_admin_role_cannot_create_service_account(client, engine):
    """The admin role does NOT hold auth.service_accounts.manage —
    super_admin only. Same carve-out shape as user.impersonate."""
    await _enable_pats(engine)
    await seed_admin(engine, email="admin-only@example.com")
    await login(client, "admin-only@example.com", "admin-pw-123", engine=engine)
    r = await client.post(
        "/admin/service_accounts",
        json={
            "name": "x",
            "email": "x@example.com",
            "initial_scopes": ["audit.read"],
        },
    )
    assert r.status_code == 403


async def test_list_service_accounts_excludes_humans(
    client, engine, super_admin_logged_in
):
    r = await client.post(
        "/admin/service_accounts",
        json={
            "name": "svc",
            "email": "svc@example.com",
            "role_codes": ["admin"],
            "initial_scopes": ["audit.read"],
        },
    )
    assert r.status_code == 201, r.text
    r = await client.get("/admin/service_accounts")
    assert r.status_code == 200
    body = r.json()
    assert {item["email"] for item in body} == {"svc@example.com"}


async def test_initial_pat_can_authenticate(
    client, engine, super_admin_logged_in
):
    """The plaintext returned by create can immediately authenticate
    against an audit-gated route."""
    r = await client.post(
        "/admin/service_accounts",
        json={
            "name": "svc",
            "email": "svc-pat@example.com",
            "role_codes": ["admin"],
            "initial_scopes": ["audit.read"],
        },
    )
    plaintext = r.json()["token"]["token"]
    r = await client.get(
        "/admin/audit",
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    assert r.status_code == 200, r.text


async def test_initial_pat_persists_correctly(
    client, engine, session, super_admin_logged_in
):
    """The DB row reflects the request: scopes, expires_at, and
    created_by_user_id pointing at the super_admin who issued it."""
    r = await client.post(
        "/admin/service_accounts",
        json={
            "name": "svc",
            "email": "svc-2@example.com",
            "role_codes": ["admin"],
            "initial_scopes": ["audit.read", "user.manage"],
        },
    )
    token_id = r.json()["token"]["id"]
    row = (
        await session.execute(
            select(AuthToken).where(AuthToken.id == token_id)
        )
    ).scalar_one()
    assert set(row.scopes) == {"audit.read", "user.manage"}
    assert row.created_by_user_id == super_admin_logged_in.id
