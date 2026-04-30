# __BRAND_NAME__

A host extension on top of [atrium](https://github.com/brendanbank/atrium).
Atrium ships the platform layer (auth, RBAC, audit, email, jobs,
notifications, admin shell); this repo adds the domain-specific routes,
models, and UI.

## Quick start

```bash
cp .env.example .env
# Edit .env: set APP_SECRET_KEY, JWT_SECRET (openssl rand -hex 48 each),
# MYSQL_PASSWORD, MYSQL_ROOT_PASSWORD.

make dev-bootstrap
make seed-admin EMAIL=you@example.com PASSWORD='a-good-password'
make seed-bundle
open http://localhost:8000
```

Sign in with the seeded admin and the **__BRAND_NAME__** card appears on
the home page, with a sidebar link to `/__HOST_NAME__`, an admin tab,
and a profile-page card. Bump the counter to exercise the RBAC + audit
path end to end.

## Layout

```
__HOST_NAME__/
  Dockerfile           # frontend-builder + FROM atrium runtime
  compose.yaml         # api + worker + mysql
  .env.example         # secrets template (copy to .env)
  Makefile             # dev-bootstrap / migrate / seed-* / test
  backend/             # host Python package (__HOST_PKG__)
    pyproject.toml
    alembic.ini
    alembic/           # alembic_version_app chain (separate from atrium)
    src/__HOST_PKG__/
      bootstrap.py     # init_app(app), init_worker(host)
      models.py        # HostBase + your tables
      router.py        # FastAPI routes
      scripts/seed_host_bundle.py
    tests/             # pytest smoke tests
  frontend/            # Vite library project (single main.js)
    package.json
    vite.config.ts     # uses @brendanbank/atrium-host-bundle-utils/vite
    src/
      main.tsx         # registry calls — ~10 lines
      api.ts
      queryClient.ts
      __BRAND_PASCAL__Widget.tsx     # home widget + admin tab + page demo
      __BRAND_PASCAL__Page.tsx
      __BRAND_PASCAL__AdminTab.tsx
      __BRAND_PASCAL__ProfileItem.tsx
    src/test/          # vitest setup + worked example using @brendanbank/atrium-test-utils
  .github/workflows/   # CI (typecheck + tests + smoke)
```

## What atrium gives you (don't reimplement)

- Auth (password / TOTP / email OTP / WebAuthn) with role-mandatory 2FA
- RBAC: roles + permissions + super_admin + impersonation
- Account lifecycle: invite-only or self-serve signup, soft-delete + grace + hard-delete
- Audit log + retention pruning
- Email pipeline: templates per locale, durable outbox, retry/backoff
- In-app notifications + SSE bell
- Admin app-config (branding, system flags, translations, auth toggles)
- Maintenance mode (super_admin bypass)

If you find yourself writing one of these, stop — atrium has it. See
the atrium repo's `CLAUDE.md` for the contract.

## What lives in this repo

- Your domain models (on `HostBase`, never `app.db.Base`)
- Your routes (gated by `current_user` or `require_perm("...")`)
- Your migrations (on the `alembic_version_app` chain)
- Your frontend pages / widgets / admin tabs
- Your background jobs (`host.scheduler.add_job` for ticks,
  `host.register_job_handler` for durable queue work)

## Adding things

| You want to add               | Where it lives                                       | Wire it via                                                                |
|-------------------------------|------------------------------------------------------|----------------------------------------------------------------------------|
| HTTP endpoint                 | `__HOST_PKG__/router.py`                             | `app.include_router(router)` in `init_app`                                 |
| New permission                | A new alembic migration                              | `seed_permissions_sync(op.get_bind(), [...], grants={...})`                |
| Recurring tick                | `__HOST_PKG__/schedule.py` async function            | `host.scheduler.add_job(fn, "interval", seconds=N, ...)` in `init_worker`  |
| Durable async job             | A handler `(session, job, payload) -> None`          | `host.register_job_handler(kind="...", handler=..., description="...")`    |
| Admin-tunable flag            | A Pydantic `BaseModel` config class                  | `register_namespace("ns", Model, public=False)` in `init_app`              |
| Per-user notification         | Inside the txn that mutated the row                  | `from app.services.notifications import notify_user`                       |
| Outbound email (queued)       | A template row in `email_templates` + a callsite     | `from app.email.sender import enqueue_and_log`                             |
| Audit row                     | Inside the txn that mutated the row                  | `from app.services.audit import record`                                    |
| Home widget                   | A React component in `frontend/src/`                 | `reg.registerHomeWidget({ key, render })`                                  |
| Dedicated route               | A page component                                     | `reg.registerRoute({ key, path, element, layout? })`                       |
| Sidebar link                  | A label + path                                       | `reg.registerNavItem({ key, label, to, icon? })`                           |
| Admin tab                     | A component, gated by a permission                   | `reg.registerAdminTab({ key, label, icon?, perm, element })`               |
| Profile-page card             | A component                                          | `reg.registerProfileItem({ key, slot?, render, condition? })`              |

For the full backend extension surface see
[atrium's `docs/new-project/README.md`](https://github.com/brendanbank/atrium/blob/master/docs/new-project/README.md).

## Tests

```bash
make test            # frontend unit tests + backend smoke tests
make typecheck       # tsc --noEmit on the host bundle
```

## Pinning atrium

`compose.yaml` reads `ATRIUM_IMAGE` from `.env` (default
`ghcr.io/brendanbank/atrium:__ATRIUM_VERSION__`). Override to test
against a specific release:

```bash
ATRIUM_IMAGE=ghcr.io/brendanbank/atrium:0.19.1 make build up
```

The frontend SDK packages
(`@brendanbank/atrium-host-types`, `@brendanbank/atrium-host-bundle-utils`,
`@brendanbank/atrium-test-utils`) version in lockstep with the image
— a pin of `^__ATRIUM_VERSION__` matches any patch of the
`__ATRIUM_VERSION__.x` line.
