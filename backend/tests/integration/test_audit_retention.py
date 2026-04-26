"""Audit-log retention pruning.

Covers the service helper plus the ``audit_prune`` handler:

- old rows past the cutoff are deleted, recent rows survive
- ``retention_days <= 0`` is the explicit "keep forever" sentinel
- a missing ``app_settings['audit']`` row is treated as "keep forever"
  rather than blowing up the worker

The ``audit`` row in ``app_settings`` is preserved across tests by the
conftest truncate-skiplist, so each test deletes the row it wrote
before yielding.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.jobs.builtin_handlers import audit_prune_handler
from app.models.enums import JobState
from app.models.ops import AppSetting, AuditLog, ScheduledJob
from app.services.audit import record as audit_record
from app.services.audit_retention import prune_audit_log
from tests.helpers import seed_admin


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _clear_audit_state(engine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await s.execute(delete(AuditLog))
        await s.execute(delete(AppSetting).where(AppSetting.key == "audit"))
        await s.commit()


async def _seed_old_audit_row(session, *, actor_user_id: int, days_ago: int) -> None:
    """INSERT an audit_log row with an explicit ``created_at`` in the
    past. ``audit.record`` relies on the column's ``server_default=NOW()``
    so it can't seed history."""
    created_at = _utcnow_naive() - timedelta(days=days_ago)
    await session.execute(
        text(
            "INSERT INTO audit_log "
            "(actor_user_id, entity, entity_id, action, diff, created_at) "
            "VALUES (:actor, 'user', :entity_id, 'old', NULL, :created_at)"
        ),
        {
            "actor": actor_user_id,
            "entity_id": actor_user_id,
            "created_at": created_at,
        },
    )


@pytest.mark.asyncio
async def test_prune_audit_log_deletes_only_old_rows(client, engine):
    _ = client  # truncate-on-teardown
    admin = await seed_admin(engine)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        # Two old rows, two recent ones.
        await _seed_old_audit_row(s, actor_user_id=admin.id, days_ago=30)
        await _seed_old_audit_row(s, actor_user_id=admin.id, days_ago=10)
        await audit_record(
            s,
            actor_user_id=admin.id,
            entity="user",
            entity_id=admin.id,
            action="recent",
        )
        await audit_record(
            s,
            actor_user_id=admin.id,
            entity="user",
            entity_id=admin.id,
            action="recent",
        )
        await s.commit()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        deleted = await prune_audit_log(s, retention_days=7)

    assert deleted == 2

    async with factory() as s:
        remaining = (
            await s.execute(select(func.count()).select_from(AuditLog))
        ).scalar_one()
        actions = (
            await s.execute(select(AuditLog.action))
        ).scalars().all()
    assert remaining == 2
    assert set(actions) == {"recent"}


@pytest.mark.asyncio
async def test_prune_audit_log_zero_is_noop(client, engine):
    _ = client
    admin = await seed_admin(engine)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await _seed_old_audit_row(s, actor_user_id=admin.id, days_ago=365)
        await s.commit()

    async with factory() as s:
        deleted = await prune_audit_log(s, retention_days=0)
    assert deleted == 0

    async with factory() as s:
        remaining = (
            await s.execute(select(func.count()).select_from(AuditLog))
        ).scalar_one()
    assert remaining == 1


@pytest.mark.asyncio
async def test_handler_uses_app_settings(client, engine):
    _ = client
    admin = await seed_admin(engine)
    await _clear_audit_state(engine)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await _seed_old_audit_row(s, actor_user_id=admin.id, days_ago=30)
        await audit_record(
            s,
            actor_user_id=admin.id,
            entity="user",
            entity_id=admin.id,
            action="recent",
        )
        s.add(AppSetting(key="audit", value={"retention_days": 7}))
        await s.commit()

    async with factory() as s:
        job = ScheduledJob(
            job_type="audit_prune",
            run_at=_utcnow_naive(),
            state=JobState.PENDING.value,
            payload={},
        )
        s.add(job)
        await s.commit()
        await audit_prune_handler(s, job, {})

    async with factory() as s:
        actions = (await s.execute(select(AuditLog.action))).scalars().all()
    assert set(actions) == {"recent"}

    await _clear_audit_state(engine)


@pytest.mark.asyncio
async def test_handler_missing_setting_is_noop(client, engine):
    _ = client
    admin = await seed_admin(engine)
    await _clear_audit_state(engine)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await _seed_old_audit_row(s, actor_user_id=admin.id, days_ago=365)
        await s.commit()

    async with factory() as s:
        job = ScheduledJob(
            job_type="audit_prune",
            run_at=_utcnow_naive(),
            state=JobState.PENDING.value,
            payload={},
        )
        s.add(job)
        await s.commit()
        # No app_settings['audit'] row → handler treats it as
        # retention_days=0 and shouldn't raise.
        await audit_prune_handler(s, job, {})

    async with factory() as s:
        remaining = (
            await s.execute(select(func.count()).select_from(AuditLog))
        ).scalar_one()
    assert remaining == 1


@pytest.mark.asyncio
async def test_handler_zero_retention_keeps_old_rows(client, engine):
    _ = client
    admin = await seed_admin(engine)
    await _clear_audit_state(engine)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await _seed_old_audit_row(s, actor_user_id=admin.id, days_ago=365)
        s.add(AppSetting(key="audit", value={"retention_days": 0}))
        await s.commit()

    async with factory() as s:
        job = ScheduledJob(
            job_type="audit_prune",
            run_at=_utcnow_naive(),
            state=JobState.PENDING.value,
            payload={},
        )
        s.add(job)
        await s.commit()
        await audit_prune_handler(s, job, {})

    async with factory() as s:
        remaining = (
            await s.execute(select(func.count()).select_from(AuditLog))
        ).scalar_one()
    assert remaining == 1

    await _clear_audit_state(engine)
