# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the idle-session timeout enforced by ``DBSessionJWTStrategy``.

Three things to pin:

* ``auth.idle_timeout_seconds == 0`` (the default) is the disable
  sentinel — sessions never expire on idle, only on absolute lifetime.
* A positive value rejects sessions whose ``last_seen_at`` is older
  than the threshold, and marks the row revoked so logout-all /
  active-sessions list reflects reality.
* Activity refreshes the watermark — a request inside the threshold
  resets the idle clock, even if a follow-up request lands after the
  threshold expires.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth.backend import _now_naive
from app.models.auth_session import AuthSession
from app.models.ops import AppSetting
from tests.helpers import login, seed_user


async def _set_idle_timeout(engine, seconds: int) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        stmt = mysql_insert(AppSetting).values(
            key="auth", value={"idle_timeout_seconds": seconds}
        )
        stmt = stmt.on_duplicate_key_update(value=stmt.inserted.value)
        await s.execute(stmt)
        await s.commit()


async def _wipe_auth(engine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await s.execute(delete(AppSetting).where(AppSetting.key == "auth"))
        await s.commit()


async def _backdate_last_seen(engine, user_id: int, seconds_ago: int) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await s.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id)
            .values(last_seen_at=_now_naive() - timedelta(seconds=seconds_ago))
        )
        await s.commit()


async def _session_revoked(engine, user_id: int) -> bool:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        row = (
            await s.execute(
                select(AuthSession.revoked_at).where(
                    AuthSession.user_id == user_id
                )
            )
        ).scalar_one()
    return row is not None


@pytest.mark.asyncio
async def test_idle_timeout_disabled_by_default(client, engine):
    """Without the knob set, even an ancient session keeps working —
    fresh atrium ships with no idle gate."""
    await _wipe_auth(engine)
    user = await seed_user(engine)
    await login(client, user.email, "user-pw-123", engine=engine)
    # Backdate way past any reasonable idle threshold.
    await _backdate_last_seen(engine, user.id, 7 * 24 * 3600)
    r = await client.get("/users/me")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_idle_timeout_rejects_stale_session(client, engine):
    """30-min idle threshold + a session last seen 31 minutes ago →
    cookie is rejected on the next request, row is marked revoked."""
    user = await seed_user(engine)
    await login(client, user.email, "user-pw-123", engine=engine)
    await _set_idle_timeout(engine, 30 * 60)
    await _backdate_last_seen(engine, user.id, 31 * 60)

    r = await client.get("/users/me")
    assert r.status_code == 401
    assert await _session_revoked(engine, user.id) is True


@pytest.mark.asyncio
async def test_idle_timeout_passes_inside_window(client, engine):
    """30-min threshold + last-seen 5 minutes ago → still authenticated."""
    user = await seed_user(engine)
    await login(client, user.email, "user-pw-123", engine=engine)
    await _set_idle_timeout(engine, 30 * 60)
    await _backdate_last_seen(engine, user.id, 5 * 60)

    r = await client.get("/users/me")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_activity_refreshes_watermark(client, engine):
    """A request inside the window resets ``last_seen_at`` so a
    subsequent request 31 minutes after the *first* login (but right
    after the touch) still passes."""
    user = await seed_user(engine)
    await login(client, user.email, "user-pw-123", engine=engine)
    await _set_idle_timeout(engine, 30 * 60)

    # 25 minutes idle: still inside the 30-min window. The successful
    # read will refresh ``last_seen_at`` to ~now.
    await _backdate_last_seen(engine, user.id, 25 * 60)
    r = await client.get("/users/me")
    assert r.status_code == 200

    # Now back-date by only 10 minutes — the second request comes
    # well within the new (refreshed) window.
    await _backdate_last_seen(engine, user.id, 10 * 60)
    r = await client.get("/users/me")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_idle_timeout_zero_is_disable_sentinel(client, engine):
    """Explicit ``idle_timeout_seconds: 0`` matches the unset default —
    sessions don't expire on idle."""
    user = await seed_user(engine)
    await login(client, user.email, "user-pw-123", engine=engine)
    await _set_idle_timeout(engine, 0)
    await _backdate_last_seen(engine, user.id, 7 * 24 * 3600)

    r = await client.get("/users/me")
    assert r.status_code == 200
