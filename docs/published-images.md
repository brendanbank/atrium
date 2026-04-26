# Published images and the host extension contract

Atrium is consumed as a **base Docker image**: a host project lives in its own
repo, `FROM`s the published atrium image, and adds bespoke functionality
through declared extension points without editing atrium files. This document
describes what gets published, where, how it's tagged, and the contract a host
app implements.

For a worked example that exercises every extension point, see
[`examples/hello-world/`](../examples/hello-world/).

---

## Image catalogue

| Image                              | Built from                                      | Roles               |
|------------------------------------|-------------------------------------------------|---------------------|
| `ghcr.io/<org>/atrium-backend`     | `backend/Dockerfile` `runtime` stage            | api **and** worker  |
| `ghcr.io/<org>/atrium-web`         | `frontend/Dockerfile` `runtime` stage           | nginx + compiled SPA |

The same `atrium-backend` image runs both the FastAPI ASGI app and the
APScheduler worker — the host's compose overrides the CMD per service:

- api: `uvicorn app.main:app --host 0.0.0.0 --port 8000` (image default)
- worker: `python -m app.worker`

`atrium-web` is nginx serving the prebuilt SPA bundle on `:8080`. It expects
to be reverse-proxied by an edge that maps `/api/*` to the api container.

## Tagging scheme

Images are published **only** on a `vX.Y.Z` git tag. One tag push produces
these registry tags:

- `X.Y.Z` — fully pinned
- `X.Y` — auto-uptake patch releases
- `X` — auto-uptake minor releases
- `latest`

There is **no** rolling `edge` tag and **no** per-commit `sha-…` tag. Master
commits are not published — every published artifact corresponds to a
deliberate version bump. Pin to `X.Y` in production for patch uptake; pin to
`X.Y.Z` for fully deterministic deploys.

Both images are built for `linux/amd64` and `linux/arm64`.

## Using atrium as a base image

A host project's `backend/Dockerfile`:

```dockerfile
ARG ATRIUM_BACKEND_IMAGE=ghcr.io/<org>/atrium-backend:1
FROM ${ATRIUM_BACKEND_IMAGE}

USER root
COPY ./host_app /opt/host_app
RUN /opt/venv/bin/pip install --no-cache-dir /opt/host_app
USER app
```

A host project's `docker-compose.yml`:

```yaml
services:
  api:
    image: ghcr.io/your-org/host-backend:1.0.0   # built from your Dockerfile above
    environment:
      ATRIUM_HOST_MODULE: host_app.bootstrap
      DATABASE_URL: mysql+aiomysql://app:secret@mysql/app
      JWT_SECRET: ${JWT_SECRET}
    depends_on: [mysql]

  worker:
    image: ghcr.io/your-org/host-backend:1.0.0
    command: ["python", "-m", "app.worker"]
    environment:
      ATRIUM_HOST_MODULE: host_app.bootstrap
      DATABASE_URL: mysql+aiomysql://app:secret@mysql/app
      JWT_SECRET: ${JWT_SECRET}

  web:
    image: ghcr.io/<org>/atrium-web:1
    # The host's own static-file server (or a separate web service)
    # serves the JS bundle the SPA dynamically imports — see
    # "Frontend extension contract" below.

  mysql:
    image: mysql:8.0
    environment:
      MYSQL_DATABASE: app
      ...
```

See [Operational notes](#operational-notes) for the full env-var split between
build-time secrets, runtime env vars, and the `app_settings` table.

---

## Backend extension contract

Atrium imports a single host module on startup, named by the
`ATRIUM_HOST_MODULE` environment variable:

```bash
ATRIUM_HOST_MODULE=host_app.bootstrap
```

The module exports two optional callables:

```python
# host_app/bootstrap.py
from fastapi import FastAPI

def init_app(app: FastAPI) -> None:
    """Called once during create_app(), after every atrium router is
    included and before the ASGI app starts serving."""
    from .router import router
    app.include_router(router)

def init_worker(scheduler) -> None:
    """Called once during worker startup, after register_builtin_handlers()
    and before scheduler.start()."""
    from app.jobs.runner import register_handler
    from .handler import my_handler

    register_handler("my_kind", my_handler)
    scheduler.add_job(my_tick, "interval", seconds=60)
```

**Ordering guarantees**:

- Atrium's routers, namespaces, and built-in handlers are all registered
  *before* the host module is imported, so `init_app` and `init_worker`
  can read atrium state safely.
- ImportError at startup is intentionally loud — the operator opted in
  by setting the env var, so a typo or missing dep should fail startup
  rather than silently launch atrium without the host.
- A module that defines neither callable is allowed (import side-effects
  alone are sufficient); atrium logs `host.init_app.absent` /
  `host.init_worker.absent` in that case.

### What the host can register

Through the registries atrium already exposes:

- **Routers** — `app.include_router(my_router)` from `init_app`.
- **App-config namespaces** — `register_namespace("my_ns", MyModel, public=False)`
  from `app.services.app_config`. Reaches the admin UI at
  `/admin/app-config` automatically.
- **Job handlers** — `register_handler("my_kind", handler)` from
  `app.jobs.runner`. The runner dispatches `scheduled_jobs` rows to
  registered handlers; unknown `job_type` values are cancelled with a
  loud `last_error` rather than retried indefinitely.
- **APScheduler jobs** — `scheduler.add_job(...)` from `init_worker`.

### Permission seeding

Two ways, same logic. Both live in `app.auth.rbac_seed`. Atrium auto-grants
every newly seeded permission to `super_admin` (matching the seed pattern in
its own `0001_atrium_init`); unknown role codes in `grants` are skipped with
a warning.

**Migration form** (recommended for static permissions):

```python
# host_app/alembic/versions/0001_my_init.py
from alembic import op
from app.auth.rbac_seed import seed_permissions_sync

def upgrade() -> None:
    op.create_table("my_thing", ...)
    seed_permissions_sync(
        op.get_bind(),
        ["my.read", "my.write"],
        grants={"admin": ["my.write"]},
    )
```

**Runtime form** (for permissions discovered at startup, e.g. plugin-loaded):

```python
# host_app/bootstrap.py
async def _seed():
    async with get_session_factory()() as session:
        await seed_permissions(
            session,
            ["my.read", "my.write"],
            grants={"admin": ["my.write"]},
        )
        await session.commit()
```

The atrium lifespan is a single context manager; calling
`app.add_event_handler("startup", _seed)` from `init_app` works in current
FastAPI but emits a deprecation warning. **Use the migration form** unless
you need runtime discovery — it sidesteps the lifespan-vs-events conflict
and matches the schema-shaped nature of permissions.

---

## Frontend extension contract

Atrium exposes four registries for the SPA. The host populates them at
runtime by serving a JS bundle that atrium dynamically imports on boot.

### How the loader works

1. Set `system.host_bundle_url` via the admin UI (or write directly to
   `app_settings`). Example: `/host/main.js`.
2. On SPA boot, atrium fetches `/app-config`, reads `host_bundle_url`,
   and `await import(url)` before mounting React.
3. The host bundle's import-time side-effects call
   `window.__ATRIUM_REGISTRY__.register*` to populate the registries.
4. Atrium mounts React; `<App />` reads `getRoutes()`, `<AppLayout />`
   reads `getNavItems()`, `<AdminPage />` reads `getAdminTabs()`,
   `<HomePage />` reads `getHomeWidgets()` — all populated.

Bundle-load failure is non-fatal: the SPA still renders, just without the
host extensions. The error is logged so a fat-fingered URL is findable in
the browser console.

### The registries

```ts
// All four exposed on window.__ATRIUM_REGISTRY__:
registerHomeWidget({ key, render })           // Card on the home page.
registerRoute({ key, path, element,           // Adds a <Route> in the
                requireAuth?, layout? })       //   app router.
registerNavItem({ key, label, to, icon?,      // Sidebar link.
                  condition? })
registerAdminTab({ key, label, icon?,         // Adds a tab to /admin.
                   perm?, element })
```

- `registerRoute`'s `requireAuth` defaults to `true`; `layout` defaults to
  `'shell'` (wraps in atrium's `AppLayout`). Set `layout: 'bare'` for a
  full-bleed page (e.g. a public landing).
- `registerNavItem`'s `condition: ({ me }) => boolean` lets host nav items
  appear conditionally (e.g. only for users holding a particular
  permission).
- `registerAdminTab`'s `perm` filters the tab on `me.permissions` — users
  who lack the code never see the tab in the markup.

Same key registered twice → last write wins, with a `console.warn`
collision notice.

### Building the host bundle

The host's frontend is a separate Vite project that emits a single ES
module. Browsers can't resolve bare module specifiers like `import 'react'`
without an import map, so the bundle has to either ship its own React or
piggy-back on atrium's via an import map. The example uses the
**self-contained bundle** pattern — simpler, no atrium-side changes
required, ~250 KB gzipped.

**Self-contained bundle** (what the example uses):

```ts
// vite.config.ts
export default defineConfig({
  build: {
    lib: { entry: 'src/main.tsx', formats: ['es'], fileName: () => 'main.js' },
  },
});
```

Bundle React, ReactDOM, Mantine, TanStack Query, everything. The host
bundle's exports are atrium-React elements (created via
`window.React.createElement`) that own a single `<div>` wrapper each;
the div's `ref` callback uses the *bundled* `createRoot` to mount the
host's React tree inside it. **Two React trees coexist in the DOM** —
atrium's React owns the shell + the wrapper element; the host's React
owns the subtree.

```tsx
// main.tsx (sketch — see examples/hello-world/frontend/src/main.tsx)
import { createRoot } from 'react-dom/client';
const AtriumReact = (window as any).React;

function makeWrapperElement(child: React.ReactElement) {
  return AtriumReact.createElement('div', {
    ref: (el: HTMLElement | null) => {
      if (!el || (el as any).__hostRoot) return;
      (el as any).__hostRoot = createRoot(el);
      (el as any).__hostRoot.render(child);
    },
  });
}

reg.registerHomeWidget({
  key: 'my-widget',
  render: () => makeWrapperElement(<MyWidget />),
});
```

This sidesteps the "two Reacts, one tree" hook-dispatcher trap: atrium's
reconciler only ever calls our wrapper element's `ref` callback, never
our component functions. Hooks inside the host subtree run under the
host's React (the one rendering them), so state, context, and queries
all behave normally.

**Tabler icons (and other hooks-free components)** *can* be passed
directly to atrium's `createElement` — they're plain SVG output with no
hook calls, so atrium's reconciler can render them without the wrapper
trick. The example does this for nav-item / admin-tab icons.

**Shared React via import map** (smaller bundle, more setup): a future
B1-side change can declare an import map mapping `react` to a URL atrium
serves. Until then, self-contained is the path of least resistance.

### Worked example: Hello World

The [`examples/hello-world/`](../examples/hello-world/) directory ships a
host bundle that registers one of every slot kind (home widget, route, nav
item, admin tab) plus the backend half (`init_app` + `init_worker`,
permission seeding, scheduler pipeline). It doubles as the smoke-test for
the slot system itself — `make smoke-hello` runs the full end-to-end spec.

---

## Migrations

Host migrations live in their own alembic chain. Same database, separate
version table — atrium owns `alembic_version`, the host owns
`alembic_version_app` (or whatever the host configures). The two heads
advance independently.

```python
# host_app/alembic/env.py (key bits)
from atrium_hello_world.models import HostBase

VERSION_TABLE = "alembic_version_app"
target_metadata = HostBase.metadata

def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()
```

The host's `HostBase = DeclarativeBase()` is **separate** from atrium's
`app.db.Base` so autogenerate only sees host tables. Never modify atrium
tables from a host migration — atrium's chain owns them, and the next
atrium upgrade may collide.

Run both chains in order:

```bash
docker compose exec api alembic upgrade head                          # atrium
docker compose exec api alembic -c /opt/host_app/alembic.ini upgrade head  # host
```

---

## Operational notes

**Pinning**: production should pin to `X.Y` for automatic patch uptake or
`X.Y.Z` for fully deterministic deploys. Dev environments can track
`latest` since there's no rolling `edge` channel.

**Rollback**: tag the previous `X.Y.Z` and re-deploy. Images are immutable
once published.

**Health endpoints**: the api image exposes `/healthz`, `/readyz`, and
`/health`. The worker has no HTTP port — disable healthchecks on it in
compose (the shared backend image's `HEALTHCHECK` curls /healthz, which
will always fail on the worker).

**Configuration split** (full details in [`CLAUDE.md`](../CLAUDE.md) under
*App configuration*):

- **Build-time**: nothing in the host image needs build args beyond
  `ATRIUM_BACKEND_IMAGE`. Frontend builds bake `VITE_API_BASE_URL` etc.
  at build time.
- **Env vars** (`.env` consumed by compose's `env_file`): secrets,
  infrastructure, build-time identity. JWT secret, DSN, WebAuthn RP ID,
  mail backend.
- **`app_settings` table**: admin-tunable runtime behavior. Branding,
  maintenance flag, announcement banner, `host_bundle_url`, password
  policy, captcha config. Mutated through `/admin/app-config`; takes
  effect within the 2-second cache TTL.

---

## Try it

The fastest way to see the contract working end to end:

```bash
git clone https://github.com/<org>/atrium
cd atrium

# Build the host frontend bundle
cd examples/hello-world/frontend && pnpm install && pnpm build && cd ../../..

# Bring up the dev stack with the example overlay
docker compose -f docker-compose.yml -f docker-compose.dev.yml \
               -f examples/hello-world/compose.yaml up -d

# Run atrium + host migrations
docker compose ... exec api alembic upgrade head
docker compose ... exec api alembic -c /host_app/alembic.ini upgrade head

# Seed an admin and the host_bundle_url
docker compose ... exec api python -m app.scripts.seed_admin \
    --email admin@example.com --password 'secret' --full-name 'Admin' --super-admin
docker compose ... exec api python -m atrium_hello_world.scripts.seed_host_bundle /host/main.js
```

Open the app, log in, and the Hello World card appears on the home page.
Flip the toggle and the counter ticks every 30 seconds.

For the automated test loop, `make smoke-hello-dev` does all of the above
plus runs the Playwright spec end to end.
