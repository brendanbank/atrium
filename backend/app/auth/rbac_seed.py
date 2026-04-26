"""Idempotent permission + role-grant seeding for atrium and host apps.

Atrium seeds its own permissions in migration 0001. Host apps need the
same pattern for their domain permissions, callable from two places:

- A migration (alembic's ``op.get_bind()`` returns a sync connection).
- The runtime ``init_app`` startup hook (an async session, see
  ``ATRIUM_HOST_MODULE`` in ``app.main``).

Both forms share the same SQL: INSERT IGNORE on ``permissions``,
INSERT IGNORE on ``role_permissions`` for each named grant, plus an
auto-grant to ``super_admin`` so a host adding a new permission doesn't
have to remember to wire the omnipotent role manually. The auto-grant
matches the seed pattern in migration 0001 (``super_admin`` cross-joins
every permission).

Unknown role codes in ``grants`` are skipped with a warning rather than
raising — host apps may opt into a smaller role set than atrium ships,
and a missing role shouldn't crash startup.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import log

_INSERT_PERM = (
    "INSERT IGNORE INTO permissions (code, description) "
    "VALUES (:code, :description)"
)

_GRANT_TO_ROLE = (
    "INSERT IGNORE INTO role_permissions (role_id, permission_code) "
    "SELECT r.id, :code FROM roles r WHERE r.code = :role_code"
)

_AUTO_GRANT_SUPER_ADMIN = (
    "INSERT IGNORE INTO role_permissions (role_id, permission_code) "
    "SELECT r.id, :code FROM roles r WHERE r.code = 'super_admin'"
)

_ROLE_EXISTS = "SELECT 1 FROM roles WHERE code = :role_code LIMIT 1"


async def seed_permissions(
    session: AsyncSession,
    perms: Iterable[str],
    *,
    grants: Mapping[str, Iterable[str]] | None = None,
) -> None:
    """Idempotently insert ``perms`` into ``permissions`` and apply
    ``grants`` (role code → permission codes) on ``role_permissions``.

    Caller is responsible for ``session.commit()`` so the seed lands in
    the same transaction as any surrounding work.
    """
    perms = list(perms)
    for code in perms:
        await session.execute(
            text(_INSERT_PERM), {"code": code, "description": None}
        )
        # Auto-grant to super_admin to mirror atrium's own seeding
        # convention; host operators expect "super_admin sees
        # everything" without per-permission ceremony.
        await session.execute(text(_AUTO_GRANT_SUPER_ADMIN), {"code": code})

    for role_code, codes in (grants or {}).items():
        if role_code == "super_admin":
            # Already covered by the auto-grant above.
            continue
        exists = (
            await session.execute(
                text(_ROLE_EXISTS), {"role_code": role_code}
            )
        ).first()
        if exists is None:
            log.warning(
                "rbac_seed.unknown_role",
                role_code=role_code,
                permissions=list(codes),
            )
            continue
        for code in codes:
            await session.execute(
                text(_GRANT_TO_ROLE),
                {"code": code, "role_code": role_code},
            )


def seed_permissions_sync(
    connection: Connection,
    perms: Iterable[str],
    *,
    grants: Mapping[str, Iterable[str]] | None = None,
) -> None:
    """Sync sibling for use inside alembic migrations.

    ``op.get_bind()`` returns a sync ``Connection``; pass it straight
    in. Same SQL as the async form, same idempotence contract.
    """
    perms = list(perms)
    for code in perms:
        connection.execute(
            text(_INSERT_PERM), {"code": code, "description": None}
        )
        connection.execute(text(_AUTO_GRANT_SUPER_ADMIN), {"code": code})

    for role_code, codes in (grants or {}).items():
        if role_code == "super_admin":
            continue
        exists = connection.execute(
            text(_ROLE_EXISTS), {"role_code": role_code}
        ).first()
        if exists is None:
            log.warning(
                "rbac_seed.unknown_role",
                role_code=role_code,
                permissions=list(codes),
            )
            continue
        for code in codes:
            connection.execute(
                text(_GRANT_TO_ROLE),
                {"code": code, "role_code": role_code},
            )


__all__ = ["seed_permissions", "seed_permissions_sync"]
