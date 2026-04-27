# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""End-to-end coverage for the invite flow.

Verifies create/list/revoke/accept, multi-role assignment on accept,
the privilege gate (only ``user.manage`` may create), and the
expired/revoked/already-accepted edge cases.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.auth import User, UserInvite
from app.models.rbac import Role, user_roles
from tests.helpers import login, seed_admin, seed_user


def _accept_payload(token: str, password: str = "fresh-pw-12345") -> dict:
    return {"token": token, "password": password}


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
async def test_admin_creates_invite_with_token(client, engine):
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)

    r = await client.post(
        "/invites",
        json={
            "email": "newbie@example.com",
            "full_name": "Newbie",
            "role_codes": ["admin"],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "newbie@example.com"
    assert body["role_codes"] == ["admin"]
    # The create response carries the token so the UI can surface a
    # copyable link; the list endpoint deliberately does not.
    assert body["token"]


@pytest.mark.asyncio
async def test_invite_requires_at_least_one_role(client, engine):
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)
    r = await client.post(
        "/invites",
        json={
            "email": "newbie@example.com",
            "full_name": "Newbie",
            "role_codes": [],
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_invite_rejects_duplicate_active(client, engine):
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)

    payload = {
        "email": "dup@example.com",
        "full_name": "Dup",
        "role_codes": ["user"],
    }
    r = await client.post("/invites", json=payload)
    assert r.status_code == 201

    r = await client.post("/invites", json=payload)
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_invite_rejects_existing_user_email(client, engine):
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)
    r = await client.post(
        "/invites",
        json={
            "email": admin.email,
            "full_name": "Already in",
            "role_codes": ["user"],
        },
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_list_omits_token(client, engine):
    """``InviteRead`` exposes the role list and timestamps but never the
    token — only the create endpoint returns that. Prevents enumeration
    via the list view."""
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)
    await client.post(
        "/invites",
        json={
            "email": "listed@example.com",
            "full_name": "L",
            "role_codes": ["user"],
        },
    )

    rows = (await client.get("/invites")).json()
    assert len(rows) == 1
    assert "token" not in rows[0]


@pytest.mark.asyncio
async def test_revoke_blocks_subsequent_accept(client, engine):
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)

    created = (
        await client.post(
            "/invites",
            json={
                "email": "revoke-me@example.com",
                "full_name": "RM",
                "role_codes": ["user"],
            },
        )
    ).json()
    invite_id = created["id"]
    token = created["token"]

    r = await client.delete(f"/invites/{invite_id}")
    assert r.status_code == 204

    # Even with the original token, accept fails.
    r = await client.post("/invites/accept", json=_accept_payload(token))
    assert r.status_code == 410


@pytest.mark.asyncio
async def test_accept_creates_user_with_all_role_codes(client, engine):
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)

    created = (
        await client.post(
            "/invites",
            json={
                "email": "multi@example.com",
                "full_name": "Multi",
                "role_codes": ["admin", "user"],
            },
        )
    ).json()
    token = created["token"]

    r = await client.post("/invites/accept", json=_accept_payload(token))
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "multi@example.com"

    # All role_codes from the invite were assigned on accept.
    assert await _user_role_codes(engine, body["user_id"]) == {"admin", "user"}


@pytest.mark.asyncio
async def test_accept_marks_invite_used(client, engine):
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)

    token = (
        await client.post(
            "/invites",
            json={
                "email": "once@example.com",
                "full_name": "Once",
                "role_codes": ["user"],
            },
        )
    ).json()["token"]

    r = await client.post("/invites/accept", json=_accept_payload(token))
    assert r.status_code == 201

    # Second use of the same token: 409 already-accepted.
    r = await client.post("/invites/accept", json=_accept_payload(token, "another-pw-12345"))
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_accept_unknown_token_is_404(client, engine):
    r = await client.post(
        "/invites/accept", json=_accept_payload("not-a-real-token")
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_accept_expired_invite_is_410(client, engine):
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)

    created = (
        await client.post(
            "/invites",
            json={
                "email": "stale@example.com",
                "full_name": "S",
                "role_codes": ["user"],
            },
        )
    ).json()
    token = created["token"]
    invite_id = created["id"]

    # Backdate the invite past its expiry; tests can't sleep their way
    # past the configured TTL.
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        invite = await s.get(UserInvite, invite_id)
        assert invite is not None
        invite.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(
            hours=1
        )
        await s.commit()

    r = await client.post("/invites/accept", json=_accept_payload(token))
    assert r.status_code == 410


@pytest.mark.asyncio
async def test_non_admin_cannot_create_invite(client, engine):
    """Atrium's plain ``user`` role doesn't hold ``user.manage`` —
    an attempt to invite should 403, not silently succeed."""
    plain = await seed_user(engine)
    await login(client, plain.email, "user-pw-123", engine=engine)

    r = await client.post(
        "/invites",
        json={
            "email": "shouldnt@example.com",
            "full_name": "X",
            "role_codes": ["user"],
        },
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_cannot_create_invite(client, engine):
    r = await client.post(
        "/invites",
        json={
            "email": "nope@example.com",
            "full_name": "N",
            "role_codes": ["user"],
        },
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_accept_creates_user_via_user_manager(client, engine):
    """The accept flow runs through the fastapi-users UserManager so
    the password is hashed (never stored plaintext) and the row passes
    the standard validators."""
    admin = await seed_admin(engine)
    await login(client, admin.email, "admin-pw-123", engine=engine)

    token = (
        await client.post(
            "/invites",
            json={
                "email": "hashed@example.com",
                "full_name": "H",
                "role_codes": ["user"],
            },
        )
    ).json()["token"]

    r = await client.post("/invites/accept", json=_accept_payload(token, "real-pw-12345"))
    assert r.status_code == 201

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        u = (
            await s.execute(select(User).where(User.email == "hashed@example.com"))
        ).scalar_one()
        # Password was hashed (bcrypt prefix) — never stored as the literal.
        assert u.hashed_password != "real-pw-12345"
        assert u.hashed_password.startswith(("$argon2", "$2b$", "$2a$"))
        assert u.is_verified is True
