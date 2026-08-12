# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Pre-delete hooks for the user lifecycle.

Atrium deletes a ``users`` row by handing it to SQLAlchemy and letting
the database's own ``ON DELETE`` rules fan out. That is sufficient for
platform-owned tables — ``auth_sessions``, ``notifications`` and
friends declare ``CASCADE``, ``audit_log.actor_user_id`` declares
``SET NULL`` so history survives with an anonymous actor.

It is *not* sufficient for a host. A host is free to declare foreign
keys into ``users.id`` with restricting semantics (and on MySQL an
omitted ``ON DELETE`` clause **is** ``RESTRICT``), at which point the
platform's delete aborts with errno 1451 and there is nothing atrium
can do about it from the inside. Hosts need somewhere to clear their
own rows first.

That is what this module is: a registry the host writes to during
``init_app`` / ``init_worker``, drained by atrium immediately before
the ``users`` row goes. A deployment that registers nothing behaves
exactly as it did before.

Failures propagate — see :func:`run_pre_user_delete_hooks`.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import log

UserDeleteHook = Callable[[AsyncSession, int], Awaitable[None]]
"""``async (session, user_id) -> None``.

Runs inside the caller's transaction, so a hook must not commit or
roll back: whatever it deletes lands atomically with the ``users`` row
itself.
"""

_hooks: dict[str, UserDeleteHook] = {}


def register_pre_user_delete(name: str, hook: UserDeleteHook) -> None:
    """Register ``hook`` to run before any user row is deleted.

    ``name`` identifies the registrant in logs and dedupes re-entrant
    registration (a host whose ``init_app`` runs in both the API and
    worker processes registers the same hook twice by design).
    Re-registering the same name replaces the previous hook and logs a
    warning, matching ``HostWorkerCtx.register_job_handler``.
    """
    if not name:
        raise ValueError("register_pre_user_delete: 'name' must be non-empty")
    if name in _hooks:
        log.warning("host.pre_user_delete.duplicate", name=name)
    _hooks[name] = hook
    log.info("host.pre_user_delete.registered", name=name)


def clear_pre_user_delete_hooks() -> None:
    """Drop every registered hook. For tests."""
    _hooks.clear()


async def run_pre_user_delete_hooks(
    session: AsyncSession, user_id: int
) -> list[str]:
    """Run every registered hook against ``user_id``; return their names.

    **Exceptions are not caught.** This is the deliberate opposite of
    ``app.jobs.runner.run_one``, where one bad handler must not bring
    the loop down. Here, a host that cannot clear its rows means the
    delete has to fail: the alternative is atrium deleting the account
    while orphan rows survive in host tables, or — where the host's FKs
    restrict — failing on the ``DELETE FROM users`` anyway, with the
    operator none the wiser about which subsystem is responsible.
    Letting the error out rolls the caller's transaction back whole and
    names the culprit.
    """
    ran: list[str] = []
    for name, hook in list(_hooks.items()):
        await hook(session, user_id)
        ran.append(name)
    if ran:
        log.info("host.pre_user_delete.ran", user_id=user_id, hooks=ran)
    return ran


__all__ = [
    "UserDeleteHook",
    "clear_pre_user_delete_hooks",
    "register_pre_user_delete",
    "run_pre_user_delete_hooks",
]
