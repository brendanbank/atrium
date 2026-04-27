# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Shared test helpers — user / role factories.

Tests create users directly via SQLAlchemy (rather than via the invite
flow) for speed. The helpers here also write the user_roles link, so
the RBAC resolver picks up the right permission set — without that, a
"seeded admin" would have empty permissions.
"""
from __future__ import annotations

from fastapi_users.password import PasswordHelper
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.auth import User
from app.models.rbac import Role, user_roles

_PASSWORD_HELPER = PasswordHelper()


async def _assign_role(session, user_id: int, role_code: str) -> None:
    role_id = (
        await session.execute(select(Role.id).where(Role.code == role_code))
    ).scalar_one()
    await session.execute(
        user_roles.insert().prefix_with("IGNORE").values(
            user_id=user_id, role_id=role_id
        )
    )


async def seed_admin(
    engine,
    *,
    email: str = "admin@example.com",
    password: str = "admin-pw-123",
    role_code: str = "admin",
    full_name: str = "Test Admin",
) -> User:
    """Create a user with the matching RBAC role."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        u = User(
            email=email,
            hashed_password=_PASSWORD_HELPER.hash(password),
            is_active=True,
            is_verified=True,
            full_name=full_name,
            preferred_language="en",
        )
        s.add(u)
        await s.flush()
        await _assign_role(s, u.id, role_code)
        await s.commit()
        await s.refresh(u)
        return u


async def seed_super_admin(engine, *, email: str = "super@example.com") -> User:
    """admin + super_admin — needed for impersonation tests."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        u = User(
            email=email,
            hashed_password=_PASSWORD_HELPER.hash("super-pw-123"),
            is_active=True,
            is_verified=True,
            full_name="Super Admin",
            preferred_language="en",
        )
        s.add(u)
        await s.flush()
        await _assign_role(s, u.id, "admin")
        await _assign_role(s, u.id, "super_admin")
        await s.commit()
        await s.refresh(u)
        return u


async def seed_user(
    engine,
    *,
    email: str = "user@example.com",
    password: str = "user-pw-123",
    role_code: str = "user",
    full_name: str = "Test User",
) -> User:
    """Plain non-admin user with the given RBAC role."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        u = User(
            email=email,
            hashed_password=_PASSWORD_HELPER.hash(password),
            is_active=True,
            is_verified=True,
            full_name=full_name,
            preferred_language="en",
        )
        s.add(u)
        await s.flush()
        await _assign_role(s, u.id, role_code)
        await s.commit()
        await s.refresh(u)
        return u


async def login_partial(client, email: str, password: str) -> None:
    """POST /auth/jwt/login only. Session is left in its default state —
    which, under mandatory 2FA, means ``totp_passed=False``. Use this in
    tests that specifically drive the TOTP / email-OTP setup or
    challenge flow."""
    r = await client.post(
        "/auth/jwt/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code in (200, 204), r.text


async def login(client, email: str, password: str, *, engine=None) -> None:
    """Default login helper: password + ``totp_passed=True``. Every
    ``AuthSession`` row created by the strategy starts partial, so tests
    that just need an authenticated actor would otherwise have to drive
    the full 2FA dance on every login. This helper short-circuits that
    by flipping the flag directly in the DB.

    When ``engine`` is omitted (legacy signature), returns after password
    login only — callers get a partial session.
    """
    await login_partial(client, email, password)
    if engine is None:
        return

    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.models.auth_session import AuthSession

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        user_id = (
            await s.execute(select(User.id).where(User.email == email))
        ).scalar_one()
        await s.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(totp_passed=True)
        )
        await s.commit()


async def login_fully_authenticated(
    client, engine, email: str, password: str
) -> None:
    """Backward-compat wrapper with a slightly different arg order.
    Prefer ``login(client, email, password, engine=engine)`` in new
    tests."""
    await login(client, email, password, engine=engine)
