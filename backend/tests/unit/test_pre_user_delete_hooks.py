# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Coverage for the host pre-user-delete hook registry (#223).

What's pinned:

* A registered hook runs, and receives the id of the user about to go.
* A hook that raises aborts the delete rather than letting atrium
  remove the account with the host's rows still behind it.
* Re-registering a name replaces rather than duplicates, so a host
  whose ``init_app`` runs in both the API and worker processes doesn't
  double-sweep.
* Registering nothing leaves the delete path exactly as it was.
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.host_sdk.user_deletion import (
    clear_pre_user_delete_hooks,
    register_pre_user_delete,
    run_pre_user_delete_hooks,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """The registry is process-global; a leaked hook would leak into
    every other test in the session."""
    clear_pre_user_delete_hooks()
    yield
    clear_pre_user_delete_hooks()


@pytest.mark.asyncio
async def test_hook_runs_with_the_target_user_id():
    seen: list[int] = []

    async def _hook(_session: AsyncSession, user_id: int) -> None:
        seen.append(user_id)

    register_pre_user_delete("pa", _hook)
    ran = await run_pre_user_delete_hooks(None, 42)  # type: ignore[arg-type]

    assert seen == [42]
    assert ran == ["pa"]


@pytest.mark.asyncio
async def test_no_hooks_registered_is_a_no_op():
    assert await run_pre_user_delete_hooks(None, 42) == []  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_a_throwing_hook_propagates():
    """Deliberately unlike the job runner, which swallows.

    If the host can't clear its rows the delete has to fail: the
    alternative is deleting the account and orphaning host data, or
    failing on the DELETE FROM users anyway with no indication of which
    subsystem is responsible.
    """

    async def _boom(_session: AsyncSession, _user_id: int) -> None:
        raise RuntimeError("host cannot clear its rows")

    register_pre_user_delete("pa", _boom)

    with pytest.raises(RuntimeError, match="host cannot clear its rows"):
        await run_pre_user_delete_hooks(None, 42)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_reregistering_a_name_replaces_it():
    calls: list[str] = []

    async def _first(_session: AsyncSession, _user_id: int) -> None:
        calls.append("first")

    async def _second(_session: AsyncSession, _user_id: int) -> None:
        calls.append("second")

    register_pre_user_delete("pa", _first)
    register_pre_user_delete("pa", _second)
    await run_pre_user_delete_hooks(None, 42)  # type: ignore[arg-type]

    assert calls == ["second"]


@pytest.mark.asyncio
async def test_every_registered_hook_runs():
    calls: list[str] = []

    async def _make(name: str):
        async def _hook(_session: AsyncSession, _user_id: int) -> None:
            calls.append(name)

        return _hook

    register_pre_user_delete("pa", await _make("pa"))
    register_pre_user_delete("other", await _make("other"))
    ran = await run_pre_user_delete_hooks(None, 42)  # type: ignore[arg-type]

    assert sorted(calls) == ["other", "pa"]
    assert sorted(ran) == ["other", "pa"]


def test_empty_name_is_rejected():
    async def _hook(_session: AsyncSession, _user_id: int) -> None:
        return None

    with pytest.raises(ValueError, match="non-empty"):
        register_pre_user_delete("", _hook)
