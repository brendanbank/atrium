# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Atrium's own fastapi-users adapter (``app.auth.db``).

It replaced ``fastapi_users_db_sqlalchemy`` so atrium could move to
SQLAlchemy 2.1. These tests pin the behaviour fastapi-users relies on:
case-insensitive email lookup, and create / update / delete committing
their own transaction (checked by re-reading through a fresh session).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.auth.db import SQLAlchemyUserDatabase
from app.models.auth import User


def _new_user() -> dict[str, object]:
    return {
        "email": "Alice@Example.com",
        "hashed_password": "x",
        "full_name": "Alice",
    }


async def _reread(engine: AsyncEngine, user_id: int) -> User | None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as fresh:
        return (
            await fresh.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()


async def test_create_commits_and_get_finds_it(
    session: AsyncSession, engine: AsyncEngine
) -> None:
    db = SQLAlchemyUserDatabase(session)
    user = await db.create(_new_user())

    assert user.id is not None
    assert user.is_active is True  # server/ORM defaults applied by refresh
    persisted = await _reread(engine, user.id)
    assert persisted is not None
    assert persisted.email == "Alice@Example.com"

    got = await db.get(user.id)
    assert got is not None and got.id == user.id


async def test_get_unknown_returns_none(session: AsyncSession) -> None:
    db = SQLAlchemyUserDatabase(session)
    assert await db.get(999_999) is None
    assert await db.get_by_email("nobody@example.com") is None


async def test_get_by_email_is_case_insensitive(session: AsyncSession) -> None:
    db = SQLAlchemyUserDatabase(session)
    user = await db.create(_new_user())

    for probe in ("alice@example.com", "ALICE@EXAMPLE.COM", "Alice@Example.com"):
        found = await db.get_by_email(probe)
        assert found is not None and found.id == user.id, probe


async def test_update_commits(session: AsyncSession, engine: AsyncEngine) -> None:
    db = SQLAlchemyUserDatabase(session)
    user = await db.create(_new_user())

    updated = await db.update(user, {"full_name": "Alice B", "is_verified": True})

    assert updated.full_name == "Alice B"
    persisted = await _reread(engine, user.id)
    assert persisted is not None
    assert persisted.full_name == "Alice B"
    assert persisted.is_verified is True


async def test_delete_commits(session: AsyncSession, engine: AsyncEngine) -> None:
    db = SQLAlchemyUserDatabase(session)
    user = await db.create(_new_user())
    user_id = user.id

    await db.delete(user)

    assert await _reread(engine, user_id) is None
