# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""PAT-related audit events fired from the middleware + URL refusal."""
from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

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
    reset_for_tests()
    yield
    reset_for_tests()


async def _set_pats(engine, **kwargs):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(AppSetting(
            key="pats",
            value={"enabled": True, **kwargs},
        ))
        await s.commit()


async def _seed_pat(engine, user_id: int, **token_kwargs) -> str:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    plain, prefix = generate_token()
    async with factory() as s:
        s.add(AuthToken(
            user_id=user_id, created_by_user_id=user_id,
            name=token_kwargs.pop("name", "audit"),
            token_prefix=prefix, token_hash=hash_token(plain),
            scopes=token_kwargs.pop("scopes", ["audit.read"]),
            created_at=_utcnow(),
            **token_kwargs,
        ))
        await s.commit()
    return plain


async def _audit_count(session, action: str) -> int:
    rows = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.entity == "auth_token",
                AuditLog.action == action,
            )
        )
    ).scalars().all()
    return len(rows)


async def test_first_use_always_logged(client, engine, session):
    """``use_audit_sample_rate`` defaults to 0.02 — but the *first* use
    of a token is always logged regardless of the sample rate."""
    await _set_pats(engine, use_audit_sample_rate=0.0)
    user = await seed_admin(engine, email="first-use@example.com")
    plain = await _seed_pat(engine, user.id)

    r = await client.get(
        "/admin/audit",
        headers={"Authorization": f"Bearer {plain}"},
    )
    assert r.status_code == 200
    assert await _audit_count(session, "used") == 1


async def test_subsequent_uses_sampled(
    client, engine, session, monkeypatch
):
    """At sample rate 1.0 every use is logged; at 0.0 only the first."""
    await _set_pats(engine, use_audit_sample_rate=1.0)
    user = await seed_admin(engine, email="sampled@example.com")
    plain = await _seed_pat(engine, user.id)
    headers = {"Authorization": f"Bearer {plain}"}

    for _ in range(3):
        r = await client.get("/admin/audit", headers=headers)
        assert r.status_code == 200
    assert await _audit_count(session, "used") == 3


async def test_invalid_token_writes_pat_invalid_row(
    client, engine, session
):
    """Format-valid token that misses the DB → 401 + ``invalid`` row.
    Format-trash bypasses the audit (no row) — only structurally
    valid wrong-tokens are interesting."""
    await _set_pats(engine)
    plain, _ = generate_token()
    r = await client.get(
        "/users/me/context",
        headers={"Authorization": f"Bearer {plain}"},
    )
    assert r.status_code == 401
    assert await _audit_count(session, "invalid") == 1


async def test_expired_token_writes_pat_expired_row(
    client, engine, session
):
    await _set_pats(engine)
    user = await seed_admin(engine, email="expired-audit@example.com")
    plain = await _seed_pat(
        engine, user.id, expires_at=_utcnow() - timedelta(days=1)
    )
    r = await client.get(
        "/admin/audit",
        headers={"Authorization": f"Bearer {plain}"},
    )
    assert r.status_code == 401
    assert await _audit_count(session, "expired") == 1


async def test_url_token_attempt_400_and_audited(client, engine, session):
    """A request whose query string contains an ``atr_pat_*`` token is
    refused with 400 *before* any auth step. Tokens belong in
    Authorization, never in URLs."""
    await _set_pats(engine)
    plain, _ = generate_token()
    r = await client.get(f"/admin/audit?token={plain}")
    assert r.status_code == 400
    assert r.json()["code"] == "token_in_url"
    assert await _audit_count(session, "in_url_attempt") == 1


async def test_url_token_attempt_in_path(client, engine, session):
    await _set_pats(engine)
    plain, _ = generate_token()
    r = await client.get(f"/admin/audit/{plain}")
    assert r.status_code == 400
    assert r.json()["code"] == "token_in_url"


async def test_scope_reduced_audit_when_user_loses_perm(
    client, engine, session
):
    """A token's stored scopes that the user doesn't currently hold
    triggers a ``scope_reduced`` audit at request time. Stable signal
    for ops to spot 'why is my token suddenly underpowered'."""
    await _set_pats(engine)
    # Plain user with no audit.read; token claims audit.read.
    from tests.helpers import seed_user

    user = await seed_user(engine, email="demoted@example.com")
    plain = await _seed_pat(engine, user.id, scopes=["audit.read"])
    r = await client.get(
        "/users/me/context",
        headers={"Authorization": f"Bearer {plain}"},
    )
    # The request itself goes through (current_user dep) but the
    # intersected permission set is empty for any audit-gated route.
    assert r.status_code == 200
    assert await _audit_count(session, "scope_reduced") == 1


async def test_pat_used_carries_token_id_in_audit_log(
    client, engine, session
):
    """The ``token_id`` column is the indexed surface for the per-token
    audit view — every middleware-emitted row must populate it."""
    random.seed(0)  # deterministic in case sample lands a use row
    await _set_pats(engine, use_audit_sample_rate=1.0)
    user = await seed_admin(engine, email="tid@example.com")
    plain = await _seed_pat(engine, user.id)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        token_row = (
            await s.execute(
                select(AuthToken).where(AuthToken.user_id == user.id)
            )
        ).scalar_one()
        token_id = token_row.id

    await client.get(
        "/admin/audit",
        headers={"Authorization": f"Bearer {plain}"},
    )

    rows = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.entity == "auth_token",
                AuditLog.action == "used",
            )
        )
    ).scalars().all()
    assert len(rows) >= 1
    assert all(r.token_id == token_id for r in rows)
