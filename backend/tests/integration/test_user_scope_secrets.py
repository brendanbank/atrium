# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Acceptance gates for user-scope secrets (issue #227).

These run against real MySQL because the properties under test are
about rows: the owner is read from the row being decrypted, and the
shred is a foreign key doing its job. A stub session would prove none
of it.

Nothing here authenticates. Every test is a plain coroutine with no
request, no ContextVar, no principal — which is the point: the host
that asked for this authenticates a *router* over HTTP Basic and has
no atrium user to hand.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import Integer, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.host_sdk.crypto import (
    MaskedSecret,
    SecretBlob,
    SecretDecryptError,
    SecretLockedError,
    SecretShreddedError,
    UserSecret,
    shred_user_key,
    unlock_user_secrets,
)
from app.models.auth import User
from app.models.user_secret_key import UserSecretKey
from tests.helpers import seed_admin


class HostBase(DeclarativeBase):
    """Stands in for a host bundle's own declarative base."""


class Device(HostBase):
    """The shape ``atrium-ddns`` described: a row that knows its owner."""

    __tablename__ = "t_device_secrets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # No real FK: host tables live on their own metadata, which is what
    # HostForeignKey exists to paper over. Irrelevant here — the owner
    # only has to be readable off the row.
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    secret_ct: Mapped[bytes | None] = mapped_column(SecretBlob(), nullable=True)

    secret = UserSecret(
        purpose="device.secret", owner_attr="user_id", column="secret_ct"
    )


@pytest_asyncio.fixture
async def host_table(engine):
    async with engine.begin() as conn:
        await conn.run_sync(HostBase.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(HostBase.metadata.drop_all)


@pytest_asyncio.fixture
async def users(engine, session):
    # ``session`` is unused but requested for its teardown: it is what
    # TRUNCATEs the atrium tables between tests, and without it the
    # second test in the file trips over the first one's users.
    a = await seed_admin(engine, email="owner-a@example.com")
    b = await seed_admin(engine, email="owner-b@example.com", role_code="user")
    return a, b


def _factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def _write_secret(engine, user_id: int, value: str) -> int:
    async with _factory(engine)() as s:
        await unlock_user_secrets(s, user_id, create=True)
        device = Device(user_id=user_id)
        device.secret = value
        s.add(device)
        await s.commit()
        return device.id


@pytest.mark.asyncio
async def test_round_trip_without_any_authenticated_user(engine, host_table, users):
    """The whole point of #227 — no request, no principal, owner off the row."""
    owner, _ = users
    device_id = await _write_secret(engine, owner.id, "tsig-secret-value")

    async with _factory(engine)() as s:
        device = await s.get(Device, device_id)
        await unlock_user_secrets(s, device.user_id)
        assert isinstance(device.secret, MaskedSecret)
        assert device.secret.reveal() == "tsig-secret-value"


@pytest.mark.asyncio
async def test_ciphertext_never_touches_the_column_in_cleartext(
    engine, host_table, users
):
    owner, _ = users
    device_id = await _write_secret(engine, owner.id, "tsig-secret-value")

    async with _factory(engine)() as s:
        raw = (
            await s.execute(select(Device.secret_ct).where(Device.id == device_id))
        ).scalar_one()
    assert b"tsig-secret-value" not in raw
    assert raw.startswith(b"ATR")
    assert raw[4] == 2  # scope byte: user


@pytest.mark.asyncio
async def test_owner_b_cannot_read_owner_a_ciphertext(engine, host_table, users):
    """Cross-row portability is what the owner-in-AAD binding closes.

    ADR 0003 had to list it as an accepted limitation of site scope;
    for a user secret it would be one tenant using another's
    credential.
    """
    owner_a, owner_b = users
    device_id = await _write_secret(engine, owner_a.id, "a-secret")

    async with _factory(engine)() as s:
        device = await s.get(Device, device_id)
        # Repoint the row at B and unlock B's key — the shape of both a
        # DB-write attacker and a buggy import path.
        device.user_id = owner_b.id
        await unlock_user_secrets(s, owner_b.id, create=True)
        with pytest.raises(SecretDecryptError, match=r"device\.secret"):
            _ = device.secret


@pytest.mark.asyncio
async def test_reading_without_unlocking_says_what_to_call(engine, host_table, users):
    owner, _ = users
    device_id = await _write_secret(engine, owner.id, "a-secret")

    async with _factory(engine)() as s:
        device = await s.get(Device, device_id)
        with pytest.raises(SecretLockedError) as exc:
            _ = device.secret
    assert "unlock_user_secrets" in str(exc.value)


@pytest.mark.asyncio
async def test_reading_a_user_with_no_key_is_not_a_silent_new_key(
    engine, host_table, users
):
    _, other = users
    with pytest.raises(SecretShreddedError):
        async with _factory(engine)() as s:
            await unlock_user_secrets(s, other.id)


@pytest.mark.asyncio
async def test_deleting_the_user_shreds_the_key(engine, host_table, users):
    """Not row deletion — the ciphertext is captured first and survives.

    This is the property the site-scope workaround could not give, and
    the reason the key is stored rather than derived: after this the
    plaintext is unrecoverable even holding SECRET_ENCRYPTION_KEY and a
    backup taken before the delete.
    """
    owner, _ = users
    device_id = await _write_secret(engine, owner.id, "doomed-secret")

    async with _factory(engine)() as s:
        captured = (
            await s.execute(select(Device.secret_ct).where(Device.id == device_id))
        ).scalar_one()
        assert captured  # the ciphertext exists right up to the delete
        user = await s.get(User, owner.id)
        await s.delete(user)
        await s.commit()

    async with _factory(engine)() as s:
        assert (
            await s.execute(
                select(UserSecretKey).where(UserSecretKey.user_id == owner.id)
            )
        ).scalar_one_or_none() is None

        # The row and its ciphertext are still there, byte for byte.
        device = await s.get(Device, device_id)
        assert device.secret_ct == captured

        with pytest.raises(SecretShreddedError):
            await unlock_user_secrets(s, owner.id)


@pytest.mark.asyncio
async def test_a_fresh_key_for_the_same_id_does_not_resurrect_the_plaintext(
    engine, host_table, users
):
    """The re-created-user case: same id, new key, old bytes stay dead."""
    owner, _ = users
    device_id = await _write_secret(engine, owner.id, "doomed-secret")

    async with _factory(engine)() as s:
        await shred_user_key(s, owner.id)
        await s.commit()

    async with _factory(engine)() as s:
        device = await s.get(Device, device_id)
        await unlock_user_secrets(s, owner.id, create=True)
        with pytest.raises(SecretDecryptError):
            _ = device.secret


@pytest.mark.asyncio
async def test_shred_reports_whether_there_was_anything_to_shred(engine, users):
    owner, other = users
    async with _factory(engine)() as s:
        await unlock_user_secrets(s, owner.id, create=True)
        await s.commit()
    async with _factory(engine)() as s:
        assert await shred_user_key(s, owner.id) is True
        assert await shred_user_key(s, other.id) is False
        await s.commit()


@pytest.mark.asyncio
async def test_secret_assigned_before_the_owner_id_still_encrypts(
    engine, host_table, users
):
    """Keyword order in a constructor should not be a crypto decision."""
    owner, _ = users
    async with _factory(engine)() as s:
        await unlock_user_secrets(s, owner.id, create=True)
        device = Device()
        device.secret = "written-first"
        device.user_id = owner.id
        s.add(device)
        await s.commit()
        device_id = device.id

    async with _factory(engine)() as s:
        device = await s.get(Device, device_id)
        await unlock_user_secrets(s, device.user_id)
        assert device.secret.reveal() == "written-first"


@pytest.mark.asyncio
async def test_clearing_sets_the_column_null(engine, host_table, users):
    owner, _ = users
    device_id = await _write_secret(engine, owner.id, "will-be-cleared")

    async with _factory(engine)() as s:
        device = await s.get(Device, device_id)
        await unlock_user_secrets(s, device.user_id)
        device.secret = None
        await s.commit()

    async with _factory(engine)() as s:
        device = await s.get(Device, device_id)
        assert device.secret_ct is None
        assert device.secret is None


@pytest.mark.asyncio
async def test_key_cache_does_not_outlive_the_session(engine, host_table, users):
    """A shred has to bite immediately; a process-global cache would
    keep handing out a key whose wrap row is already gone."""
    owner, _ = users
    device_id = await _write_secret(engine, owner.id, "a-secret")

    async with _factory(engine)() as s:
        device = await s.get(Device, device_id)
        with pytest.raises(SecretLockedError):
            _ = device.secret


@pytest.mark.asyncio
async def test_rotating_only_the_secret_on_a_clean_row_persists(
    engine, host_table, users
):
    """Issue #230: the shape of "the user changed only the credential".

    ``__set__`` parks the plaintext in an unmapped ``__dict__`` slot,
    so without an explicit ``flag_dirty`` the row never reaches
    ``session.dirty`` and ``before_flush`` never visits it. The commit
    then succeeds with the old ciphertext still in the column -- no
    exception, no warning, a 200 back to whoever asked.

    The tests above all mutate something else on the row (or create it
    outright), which marks it dirty for free and hides this.
    """
    owner, _ = users
    device_id = await _write_secret(engine, owner.id, "original-secret")

    async with _factory(engine)() as s:
        device = await s.get(Device, device_id)  # clean, persistent
        await unlock_user_secrets(s, device.user_id)
        device.secret = "rotated-secret"  # nothing else on the row changes
        await s.commit()

    async with _factory(engine)() as s:
        device = await s.get(Device, device_id)
        await unlock_user_secrets(s, device.user_id)
        assert device.secret.reveal() == "rotated-secret"


@pytest.mark.asyncio
async def test_rotating_twice_in_a_row_keeps_the_last_value(
    engine, host_table, users
):
    """A rotation is not a one-shot: the second one has to land too.

    Guards the fix being a stale-dirty-flag artefact rather than the
    write genuinely being tracked -- if the row only happened to be
    dirty from the previous statement, the second rotation would be
    the one to fall through.
    """
    owner, _ = users
    device_id = await _write_secret(engine, owner.id, "first")

    for value in ("second", "third"):
        async with _factory(engine)() as s:
            device = await s.get(Device, device_id)
            await unlock_user_secrets(s, device.user_id)
            device.secret = value
            await s.commit()

    async with _factory(engine)() as s:
        device = await s.get(Device, device_id)
        await unlock_user_secrets(s, device.user_id)
        assert device.secret.reveal() == "third"
