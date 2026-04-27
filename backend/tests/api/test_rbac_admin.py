# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Role admin CRUD + privilege-escalation guard on user role assignment.

Two surfaces to pin down:

* /admin/roles — owner can list/create/patch/delete non-system roles;
  system roles ('owner', 'agent', 'super_admin') refuse rename + delete
  but accept permission toggles.
* PATCH /admin/users/{id}.role_ids — an actor can only grant a role
  whose permissions are a subset of their own. Without this guard a
  plain owner could self-promote to super_admin.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.rbac import Role
from tests.helpers import login, seed_admin, seed_super_admin


async def _role_id(engine, code: str) -> int:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        return (
            await s.execute(select(Role.id).where(Role.code == code))
        ).scalar_one()


# -------- CRUD --------


@pytest.mark.asyncio
async def test_owner_lists_seeded_roles(client, engine):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)
    r = await client.get("/admin/roles")
    assert r.status_code == 200
    codes = {row["code"] for row in r.json()}
    # Every migration-seeded role shows up.
    assert {"admin", "user", "super_admin"} <= codes


@pytest.mark.asyncio
async def test_create_custom_role(client, engine):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)
    r = await client.post(
        "/admin/roles",
        json={
            "code": "viewer",
            "name": "Viewer",
            "permissions": ["audit.read", "email_template.manage"],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["is_system"] is False
    assert set(body["permissions"]) == {"audit.read", "email_template.manage"}


@pytest.mark.asyncio
async def test_duplicate_role_code_conflicts(client, engine):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)
    r = await client.post(
        "/admin/roles",
        json={"code": "admin", "name": "Dup", "permissions": []},
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_unknown_permission_rejected(client, engine):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)
    r = await client.post(
        "/admin/roles",
        json={
            "code": "weird",
            "name": "Weird",
            "permissions": ["not.a.real.permission"],
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_system_role_cannot_be_renamed(client, engine):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)
    role_id = await _role_id(engine, "admin")
    r = await client.patch(
        f"/admin/roles/{role_id}", json={"name": "Renamed Owner"}
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_system_role_permissions_are_editable(client, engine):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)
    role_id = await _role_id(engine, "user")
    r = await client.patch(
        f"/admin/roles/{role_id}",
        json={"permissions": ["reminder_rule.manage"]},
    )
    assert r.status_code == 200
    assert r.json()["permissions"] == ["reminder_rule.manage"]


@pytest.mark.asyncio
async def test_system_role_cannot_be_deleted(client, engine):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)
    role_id = await _role_id(engine, "user")
    r = await client.delete(f"/admin/roles/{role_id}")
    assert r.status_code == 400


# -------- privilege-escalation guard --------


@pytest.mark.asyncio
async def test_plain_owner_cannot_grant_super_admin(client, engine):
    owner = await seed_admin(engine)  # no super_admin role
    target = await seed_admin(engine, email="target@example.com")
    await login(client, owner.email, "admin-pw-123", engine=engine)

    super_admin_role_id = await _role_id(engine, "super_admin")
    owner_role_id = await _role_id(engine, "admin")

    r = await client.patch(
        f"/admin/users/{target.id}",
        json={"role_ids": [owner_role_id, super_admin_role_id]},
    )
    # The actor doesn't hold user.impersonate (or any super_admin-only
    # permission), so granting super_admin is refused.
    assert r.status_code == 403
    assert "don't hold" in r.json()["detail"]


@pytest.mark.asyncio
async def test_super_admin_can_grant_super_admin(client, engine):
    super_a = await seed_super_admin(engine)
    target = await seed_admin(engine, email="target@example.com")
    await login(client, super_a.email, "super-pw-123", engine=engine)

    super_admin_role_id = await _role_id(engine, "super_admin")
    owner_role_id = await _role_id(engine, "admin")

    r = await client.patch(
        f"/admin/users/{target.id}",
        json={"role_ids": [owner_role_id, super_admin_role_id]},
    )
    assert r.status_code == 200, r.text
    assert set(r.json()["role_ids"]) == {owner_role_id, super_admin_role_id}


@pytest.mark.asyncio
async def test_cannot_strip_own_user_manage(client, engine):
    owner = await seed_admin(engine)
    await login(client, owner.email, "admin-pw-123", engine=engine)

    # Create a role that doesn't have user.manage.
    r = await client.post(
        "/admin/roles",
        json={
            "code": "no_manage",
            "name": "No manage",
            "permissions": ["email_template.manage"],
        },
    )
    assert r.status_code == 201
    new_role_id = r.json()["id"]

    r = await client.patch(
        f"/admin/users/{owner.id}", json={"role_ids": [new_role_id]}
    )
    # Self-edit guard refuses — otherwise owner locks themselves out.
    assert r.status_code == 400
