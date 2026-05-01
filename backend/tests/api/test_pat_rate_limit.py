# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Per-token rate limit + audit row."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth.pat_format import generate_token
from app.auth.pat_hashing import hash_token
from app.models.auth_token import AuthToken
from app.models.ops import AppSetting, AuditLog
from app.services.pat_rate_limit import reset_for_tests
from tests.helpers import seed_admin


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@pytest.fixture(autouse=True)
def _reset_pat_rate_limit():
    """The rate-limit window is process-wide (in-memory deque). Reset
    between tests so we don't leak state."""
    reset_for_tests()
    yield
    reset_for_tests()


async def _seed_pat(engine, user_id: int) -> str:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    plain, prefix = generate_token()
    async with factory() as s:
        s.add(AuthToken(
            user_id=user_id, created_by_user_id=user_id, name="rl",
            token_prefix=prefix, token_hash=hash_token(plain),
            scopes=["audit.read"], created_at=_utcnow(),
        ))
        await s.commit()
    return plain


async def _set_pats(engine, **kwargs):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(AppSetting(
            key="pats",
            value={"enabled": True, **kwargs},
        ))
        await s.commit()


async def test_exceeding_rate_limit_returns_429(client, engine):
    await _set_pats(engine, default_rate_limit_per_minute=3)
    user = await seed_admin(engine, email="rl@example.com")
    plain = await _seed_pat(engine, user.id)

    headers = {"Authorization": f"Bearer {plain}"}
    # First three pass, fourth must 429.
    for _ in range(3):
        r = await client.get("/admin/audit", headers=headers)
        assert r.status_code == 200, r.text
    r = await client.get("/admin/audit", headers=headers)
    assert r.status_code == 429
    assert "Retry-After" in r.headers
    assert r.json()["code"] == "rate_limited"


async def test_rate_limit_writes_audit_row(client, engine, session):
    await _set_pats(engine, default_rate_limit_per_minute=2)
    user = await seed_admin(engine, email="rl-audit@example.com")
    plain = await _seed_pat(engine, user.id)

    headers = {"Authorization": f"Bearer {plain}"}
    for _ in range(2):
        await client.get("/admin/audit", headers=headers)
    r = await client.get("/admin/audit", headers=headers)
    assert r.status_code == 429

    rows = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.entity == "auth_token",
                AuditLog.action == "rate_limited",
            )
        )
    ).scalars().all()
    assert len(rows) >= 1
    assert rows[0].diff["limit_per_minute"] == 2


async def test_separate_tokens_have_separate_buckets(client, engine):
    """One rate-limited token must not slow another."""
    await _set_pats(engine, default_rate_limit_per_minute=2)
    user = await seed_admin(engine, email="rl-multi@example.com")
    plain1 = await _seed_pat(engine, user.id)
    plain2 = await _seed_pat(engine, user.id)

    h1 = {"Authorization": f"Bearer {plain1}"}
    h2 = {"Authorization": f"Bearer {plain2}"}
    for _ in range(2):
        assert (await client.get("/admin/audit", headers=h1)).status_code == 200
    # Token 1 is now spent; token 2 still has its full budget.
    assert (await client.get("/admin/audit", headers=h1)).status_code == 429
    assert (await client.get("/admin/audit", headers=h2)).status_code == 200
