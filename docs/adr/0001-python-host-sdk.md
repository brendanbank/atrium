# ADR 0001 — `app.host_sdk` namespace for Python host helpers

Status: accepted, 2026-04-28

## Context

Atrium ships a host-extension contract today: a host module with
`init_app(app)` / `init_worker(scheduler)`, a separate `HostBase`
declarative base for host models, a separate alembic chain with its
own version table, and registry hooks on the frontend. Hosts re-derive
the same boilerplate every time — most painfully, the workaround
needed to declare a foreign key from a host table to an atrium table
without crashing the SQLAlchemy mapper at class-init.

Issue #42 (this epic, wave 1) introduces the first piece of typed
Python helper surface for hosts: a `HostForeignKey()` factory plus an
alembic autogenerate hook. Issue #44 will add a typed
`register_job_handler()` for the worker queue. There will be more —
the host SDK is a long-running surface, not a single helper.

We need a stable home for these helpers that:

- ships **inside** the atrium image (no separate package to publish),
  since hosts already `FROM` the atrium image and import from `app.*`;
- is **flat and discoverable** — `from app.host_sdk.db import
  HostForeignKey` reads naturally and signals "this is host-facing";
- doesn't pull alembic / SQLAlchemy bits into a host's runtime path
  unless the host actually imports them;
- separates host-facing helpers from atrium's internal services
  (`app.services.*`) so we don't accidentally promise stability on
  internal symbols.

## Decision

Add a top-level `app.host_sdk` package. Submodules group helpers by
the SDK seam they cover:

- `app.host_sdk.db` — model/declarative helpers (this PR:
  `HostForeignKey`).
- `app.host_sdk.alembic` — alembic env.py helpers (this PR:
  `emit_host_foreign_keys`).
- `app.host_sdk.jobs` — worker registry helpers (issue #44).

Imports are **explicit per submodule**. The package `__init__` does
not re-export anything; this keeps `app.host_sdk` importable from
contexts that don't have alembic on the path (e.g. a host's runtime
process that only needs `HostForeignKey` for ORM mapping, never the
autogenerate hook).

### What stays in `app.services.*`

Atrium's own services — `audit`, `email_outbox`, `password_policy`,
`captcha`, `maintenance`, etc. — stay where they are. They're
internal: their signatures may change between atrium minor versions,
their docstrings document atrium-side concerns, and host code that
reaches into them does so at its own risk. The split is

- `app.host_sdk.*` — public, typed, semver-stable across atrium
  minor versions, documented in `docs/host-models.md` and successors.
- `app.services.*` — internal, may break across any release.

## Consequences

- Future host helpers land under `app.host_sdk.<area>` without
  another ADR. The "is this host-facing?" question is answered by
  whether host code is meant to import it.
- The sibling submodules-without-cross-imports rule means the
  package `__init__` stays empty. If we later want to add a
  convenience facade (`from app.host_sdk import HostForeignKey`), we
  do so behind explicit imports inside `__init__` — but only when
  the savings actually matter.
- Documentation cross-links go to `docs/host-models.md` and similar
  topical pages, not to a single "SDK reference" page. Hosts find
  helpers by the problem they solve, not by alphabetical listing.
