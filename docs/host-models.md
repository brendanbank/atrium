# Host models — cross-base foreign keys

Host bundles declare their own SQLAlchemy models on a separate
`DeclarativeBase` (conventionally `HostBase`) so the host's alembic
chain and atrium's chain stay isolated. That isolation is
load-bearing — atrium can ship a new migration without fighting the
host's autogenerate, and the host can ship a migration without
touching atrium's tables.

The catch: a column-level `ForeignKey("users.id")` on a host model
points at a table in atrium's metadata, which sits behind a different
`Base`. SQLAlchemy resolves `ForeignKey(...)` within a single
`MetaData` and raises a cross-metadata error at mapper-init when the
target isn't there.

## TL;DR

Use `HostForeignKey` from `app.host_sdk.db` instead of a plain
`ForeignKey` whenever the target table lives in atrium's metadata.
Wire `emit_host_foreign_keys` into the host's `alembic/env.py`. The
constraint will land in the database the same way a normal model-
level FK does.

```python
# host backend/src/<pkg>/models.py
from sqlalchemy import Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.host_sdk.db import HostForeignKey


class HostBase(DeclarativeBase):
    pass


class Booking(HostBase):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(
        Integer,
        HostForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
```

```python
# host backend/alembic/env.py — additions only
from app.host_sdk.alembic import emit_host_foreign_keys

def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        process_revision_directives=emit_host_foreign_keys,
        include_object=_include_object,  # see "Filtering atrium tables"
    )
    ...
```

After that, `alembic revision --autogenerate -m "add bookings"`
emits a migration containing:

```python
op.create_table(
    "bookings",
    sa.Column("id", sa.Integer(), nullable=False),
    sa.Column("name", sa.String(length=200), nullable=False),
    sa.Column("created_by_user_id", sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(
        ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
    ),
    sa.PrimaryKeyConstraint("id"),
)
```

`alembic upgrade head` applies it; runtime FK behaviour is identical
to a normal model-level FK because the constraint exists in MySQL.

## What the helper does (and doesn't)

`HostForeignKey(target, *, ondelete=None, onupdate=None, name=None)`
returns a `SchemaItem` that, when SQLAlchemy attaches it to a
column during `Column.__init__`, stamps a marker into `Column.info`
under the key `atrium_host_fks`. **No `ForeignKey` is registered**
against the host's metadata, so the mapper sees a plain integer
column and never tries to resolve `users.id`.

`emit_host_foreign_keys` is a `process_revision_directives`
callback. At autogenerate time it walks every `MigrationScript`,
finds `CreateTableOp` and `AddColumnOp` instances on host tables,
reads the `atrium_host_fks` markers off each column, and adds a
matching `ForeignKeyConstraint` (for `CreateTableOp`) or sibling
`CreateForeignKeyOp` (for `AddColumnOp`).

What that means in practice:

- `relationship()` on the host model toward an atrium model still
  doesn't work — there's no ORM-level FK to follow. When you need
  the atrium row, load it explicitly: `await session.get(User, booking.created_by_user_id)`.
- The constraint name comes from alembic / SQLAlchemy by default.
  Pass `name="..."` to `HostForeignKey` if your project enforces a
  naming convention.
- `onupdate` is supported for symmetry with `sa.ForeignKey` even
  though atrium's existing FKs don't use it.
- A typo in the target string (`"usersid"` instead of `"users.id"`)
  is logged at WARNING and skipped — autogenerate completes, the
  operator sees the warning in alembic output. The mapper never
  validates the target, so a non-existent atrium table only surfaces
  at `alembic upgrade` time as a MySQL FK error.

## Filtering atrium tables out of autogenerate

Atrium and the host share one MySQL database. Without an
`include_object` filter, autogenerate sees atrium's tables as "in
the DB but not in `HostBase.metadata`" and proposes `drop_table` ops
for every one of them on the first autogenerate run. The
hello-world example shows the standard guard:

```python
def _include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table":
        return name in target_metadata.tables
    if reflected:
        parent = getattr(obj, "table", None)
        if parent is not None and parent.name not in target_metadata.tables:
            return False
    return True
```

Wire it into the same `context.configure(...)` call as
`process_revision_directives`. Every host alembic env.py needs it,
not just hosts using `HostForeignKey`.

## Why not just share `Base`?

Two reasons:

1. **Autogenerate isolation.** With `target_metadata = Base.metadata`,
   the host's `alembic revision --autogenerate` would see atrium's
   tables and the host's tables together. The host's chain would
   propose modifications to atrium tables, and atrium's chain would
   propose modifications to the host's. They'd fight.
2. **Independent alembic chains.** Atrium ships its own migrations
   under `backend/alembic/versions/` with their own version table
   (`alembic_version`). The host owns a separate chain
   (`alembic_version_app`). Sharing `Base` would not, in itself,
   merge the chains, but it would constantly tempt host migrations
   to touch atrium tables — the next atrium upgrade would then race
   the host migration on the same row.

`HostForeignKey` keeps the metadata split clean and gives the host
the FK declaration that's been missing.

## Worked example

`examples/hello-world/` exercises the helper end-to-end. The
relevant pieces:

- `backend/src/atrium_hello_world/models.py` — `HelloMessage` declares
  `created_by_user_id` with `HostForeignKey("users.id", ondelete="RESTRICT")`.
- `backend/alembic/env.py` — wires `emit_host_foreign_keys` and the
  `_include_object` filter into both `run_migrations_offline` and
  `do_run_migrations`.
- `backend/alembic/versions/0002_hello_messages.py` — produced by
  `alembic revision --autogenerate`. The `ForeignKeyConstraint`
  against `users.id` came from the helper, not from a hand-edit.

## See also

- ADR `docs/adr/0001-python-host-sdk.md` — why the helper lives at
  `app.host_sdk` rather than under `app.services` or in a separate
  package.
- `docs/published-images.md` — *Migrations* section.
- `docs/new-project/README.md` — *Referencing atrium tables from
  host models*.
- `docs/new-project/SKILL.md` — agent-driveable bootstrap that wires
  the helper in by default.
