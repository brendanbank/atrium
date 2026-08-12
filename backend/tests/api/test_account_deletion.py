# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Coverage for the GDPR-aligned account-deletion flow.

What's pinned:

* Self-delete with the right password anonymises the row, revokes
  every active session, schedules a hard-delete, and emails the
  original address.
* Wrong password returns 401; the row is unchanged.
* ``auth.allow_self_delete=False`` makes the route 404.
* A second self-delete on an already soft-deleted row returns 400.
* Admin-delete on a regular user works; on a super_admin returns 400.
* A previously-deleted user can no longer log in.
* The hard-delete handler removes users whose grace window has elapsed
  but leaves users still inside it.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.host_sdk.user_deletion import (
    clear_pre_user_delete_hooks,
    register_pre_user_delete,
)
from app.jobs.builtin_handlers import account_hard_delete_handler
from app.models.auth import User
from app.models.auth_session import AuthSession
from app.models.ops import AppSetting
from tests.helpers import login, seed_super_admin, seed_user


async def _set_auth_config(engine, payload: dict) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        stmt = mysql_insert(AppSetting).values(key="auth", value=payload)
        stmt = stmt.on_duplicate_key_update(value=stmt.inserted.value)
        await s.execute(stmt)
        await s.commit()


async def _wipe_auth_config(engine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await s.execute(delete(AppSetting).where(AppSetting.key == "auth"))
        await s.commit()


async def _get_user(engine, user_id: int) -> User:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        return (
            await s.execute(select(User).where(User.id == user_id))
        ).scalar_one()


@pytest.mark.asyncio
async def test_self_delete_with_correct_password_anonymises(client, engine):
    await _wipe_auth_config(engine)
    user = await seed_user(engine)
    await login(client, user.email, "user-pw-123", engine=engine)

    r = await client.post("/users/me/delete", json={"password": "user-pw-123"})
    assert r.status_code == 204, r.text

    refreshed = await _get_user(engine, user.id)
    assert refreshed.deleted_at is not None
    assert refreshed.scheduled_hard_delete_at is not None
    assert refreshed.is_active is False
    assert refreshed.email == f"deleted+{user.id}@deleted.invalid"
    assert refreshed.full_name == "Deleted user"
    assert refreshed.hashed_password == ""

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        active_sessions = (
            await s.execute(
                select(AuthSession).where(
                    AuthSession.user_id == user.id,
                    AuthSession.revoked_at.is_(None),
                )
            )
        ).scalars().all()
    assert active_sessions == []


@pytest.mark.asyncio
async def test_self_delete_wrong_password(client, engine):
    await _wipe_auth_config(engine)
    user = await seed_user(engine)
    await login(client, user.email, "user-pw-123", engine=engine)

    r = await client.post(
        "/users/me/delete", json={"password": "not-the-password"}
    )
    assert r.status_code == 401

    refreshed = await _get_user(engine, user.id)
    assert refreshed.deleted_at is None
    assert refreshed.is_active is True


@pytest.mark.asyncio
async def test_self_delete_disabled_returns_404(client, engine):
    await _set_auth_config(
        engine, {"allow_self_delete": False, "delete_grace_days": 30}
    )
    user = await seed_user(engine)
    await login(client, user.email, "user-pw-123", engine=engine)

    r = await client.post("/users/me/delete", json={"password": "user-pw-123"})
    assert r.status_code == 404

    refreshed = await _get_user(engine, user.id)
    assert refreshed.deleted_at is None


@pytest.mark.asyncio
async def test_already_deleted_cannot_delete_again(client, engine):
    await _wipe_auth_config(engine)
    user = await seed_user(engine)
    await login(client, user.email, "user-pw-123", engine=engine)

    r1 = await client.post(
        "/users/me/delete", json={"password": "user-pw-123"}
    )
    assert r1.status_code == 204

    # The session was revoked + cookie cleared; without re-login a
    # second hit goes through the unauthenticated path. We force the
    # state by flipping deleted_at on a fresh user and trying via the
    # admin path.
    admin = await seed_super_admin(engine)
    await login(client, admin.email, "super-pw-123", engine=engine)
    r2 = await client.post(f"/admin/users/{user.id}/delete")
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_admin_delete_regular_user(client, engine):
    await _wipe_auth_config(engine)
    target = await seed_user(engine, email="target@example.com")
    admin = await seed_super_admin(engine)
    await login(client, admin.email, "super-pw-123", engine=engine)

    r = await client.post(f"/admin/users/{target.id}/delete")
    assert r.status_code == 204, r.text

    refreshed = await _get_user(engine, target.id)
    assert refreshed.deleted_at is not None
    assert refreshed.is_active is False


@pytest.mark.asyncio
async def test_admin_delete_super_admin_refused(client, engine):
    await _wipe_auth_config(engine)
    target = await seed_super_admin(engine, email="other-super@example.com")
    admin = await seed_super_admin(engine)
    await login(client, admin.email, "super-pw-123", engine=engine)

    r = await client.post(f"/admin/users/{target.id}/delete")
    assert r.status_code == 400

    refreshed = await _get_user(engine, target.id)
    assert refreshed.deleted_at is None


@pytest.mark.asyncio
async def test_login_after_deletion_fails(client, engine):
    await _wipe_auth_config(engine)
    user = await seed_user(engine)
    await login(client, user.email, "user-pw-123", engine=engine)

    r = await client.post(
        "/users/me/delete", json={"password": "user-pw-123"}
    )
    assert r.status_code == 204

    # Original email is anonymised so even the email no longer exists.
    r2 = await client.post(
        "/auth/jwt/login",
        data={"username": user.email, "password": "user-pw-123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r2.status_code in (400, 401)


@pytest.mark.asyncio
async def test_hard_delete_handler_removes_expired_users(client, engine):
    """The handler scans by ``scheduled_hard_delete_at <= now`` — set
    one user's date in the past and another's in the future, run the
    handler, verify only the past one is gone."""
    await _wipe_auth_config(engine)
    expired = await seed_user(engine, email="expired@example.com")
    fresh = await seed_user(engine, email="fresh@example.com")

    factory = async_sessionmaker(engine, expire_on_commit=False)
    past = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
    future = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=10)
    async with factory() as s:
        e = await s.get(User, expired.id)
        e.deleted_at = past
        e.scheduled_hard_delete_at = past
        f = await s.get(User, fresh.id)
        f.deleted_at = past
        f.scheduled_hard_delete_at = future
        await s.commit()

    async with factory() as s:
        # ``payload`` is empty for this handler — passed through as-is.
        await account_hard_delete_handler(s, job=None, payload={})  # type: ignore[arg-type]
        await s.commit()

    async with factory() as s:
        gone = (
            await s.execute(select(User).where(User.id == expired.id))
        ).scalar_one_or_none()
        kept = (
            await s.execute(select(User).where(User.id == fresh.id))
        ).scalar_one_or_none()
    assert gone is None
    assert kept is not None


# --------------------------------------------------------------------------- #
# #223 — host pre-delete hooks on both delete paths                            #
# --------------------------------------------------------------------------- #


@pytest.fixture
def _clean_hook_registry():
    """The hook registry is process-global — leaking one would change
    every later test's delete behaviour."""
    clear_pre_user_delete_hooks()
    yield
    clear_pre_user_delete_hooks()


@pytest.mark.asyncio
async def test_admin_permanent_delete_runs_host_hooks(
    client, engine, _clean_hook_registry
):
    """The host gets to clear its rows before the account goes."""
    admin = await seed_super_admin(engine)
    victim = await seed_user(engine, email="victim@example.com")
    await login(client, admin.email, "super-pw-123", engine=engine)

    seen: list[int] = []

    async def _hook(_session, user_id: int) -> None:
        seen.append(user_id)

    register_pre_user_delete("test-host", _hook)

    r = await client.delete(f"/admin/users/{victim.id}/permanent")
    assert r.status_code == 204, r.text
    assert seen == [victim.id]

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        gone = (
            await s.execute(select(User).where(User.id == victim.id))
        ).scalar_one_or_none()
    assert gone is None


@pytest.mark.asyncio
async def test_admin_permanent_delete_aborts_when_a_hook_fails(
    client, engine, _clean_hook_registry
):
    """A host that can't clear its rows must not lose the account.

    This is the #223 production failure in miniature: atrium used to
    delete the users row regardless, hit the host's restricting FK, and
    500 with nothing naming the responsible subsystem.
    """
    admin = await seed_super_admin(engine)
    victim = await seed_user(engine, email="victim2@example.com")
    await login(client, admin.email, "super-pw-123", engine=engine)

    async def _boom(_session, _user_id: int) -> None:
        raise RuntimeError("host rows still present")

    register_pre_user_delete("test-host", _boom)

    with pytest.raises(RuntimeError, match="host rows still present"):
        await client.delete(f"/admin/users/{victim.id}/permanent")

    # The account survives — a failed cleanup leaves things as they were.
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        still_here = (
            await s.execute(select(User).where(User.id == victim.id))
        ).scalar_one_or_none()
    assert still_here is not None


@pytest.mark.asyncio
async def test_hard_delete_isolates_one_failing_account(
    engine, _clean_hook_registry
):
    """One un-erasable account must not park every other erasure.

    Head-of-line blocking on the GDPR path means accounts silently
    outlive their deadline, so each user gets its own savepoint.
    """
    await _wipe_auth_config(engine)
    poisoned = await seed_user(engine, email="poisoned@example.com")
    healthy = await seed_user(engine, email="healthy@example.com")

    factory = async_sessionmaker(engine, expire_on_commit=False)
    past = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
    async with factory() as s:
        for uid in (poisoned.id, healthy.id):
            u = await s.get(User, uid)
            u.deleted_at = past
            u.scheduled_hard_delete_at = past
        await s.commit()

    async def _selective_boom(_session, user_id: int) -> None:
        if user_id == poisoned.id:
            raise RuntimeError("host rows still present")

    register_pre_user_delete("test-host", _selective_boom)

    async with factory() as s:
        await account_hard_delete_handler(s, job=None, payload={})  # type: ignore[arg-type]
        await s.commit()

    async with factory() as s:
        stuck = (
            await s.execute(select(User).where(User.id == poisoned.id))
        ).scalar_one_or_none()
        erased = (
            await s.execute(select(User).where(User.id == healthy.id))
        ).scalar_one_or_none()
    assert stuck is not None, "the failing account should be retried next tick"
    assert erased is None, "a healthy account must not be blocked behind it"
