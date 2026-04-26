# Hello World example

A minimal host extension for atrium that exercises every B1 slot kind end
to end. Doubles as the live contract for the published-image extension
model — if this stops working, [`docs/published-images.md`](../../docs/published-images.md)
is lying.

## What it demonstrates

| Atrium extension point        | How the example uses it                          |
|-------------------------------|---------------------------------------------------|
| `ATRIUM_HOST_MODULE` bootstrap | `atrium_hello_world.bootstrap.init_app/init_worker` |
| `app.include_router`           | `/hello/state` (auth) and `/hello/toggle` (perm)  |
| `seed_permissions_sync`        | Seeds `hello.toggle` in the host alembic migration |
| `register_handler`             | `hello_count` handler increments the counter       |
| APScheduler `add_job`          | 30 s tick (2 s in tests) enqueues `hello_count` jobs |
| Host alembic chain             | Own `hello_state` table in `alembic_version_app`  |
| `registerHomeWidget`           | Card on the home page                             |
| `registerRoute`                | Dedicated `/hello` page                           |
| `registerNavItem`              | Sidebar link                                      |
| `registerAdminTab`             | Admin tab gated by `hello.toggle`                 |

## Layout

```
examples/hello-world/
  backend/                       Host backend package (atrium-hello-world)
    pyproject.toml
    src/atrium_hello_world/      bootstrap, models, router, handler,
                                 schedule, scripts/seed_host_bundle
    alembic/                     Host alembic chain (alembic_version_app)
    Dockerfile                   FROM atrium-backend + pip install
  frontend/                      Vite library project that emits a single
                                 ES module loaded by atrium dynamically
  tests-e2e/                     Playwright smoke spec
  playwright.config.ts
  compose.yaml                   Standalone demo overlay (30 s tick)
  compose.dev.yaml               Smoke variant: HELLO_TICK_SECONDS=2
  compose.e2e.yaml               Prod-images variant for CI
```

## Running it as a demo

```bash
# 1. Build the host frontend bundle
cd examples/hello-world/frontend && pnpm install && pnpm build && cd ../../..

# 2. Bring up the dev stack with the example overlay
docker compose -f docker-compose.yml -f docker-compose.dev.yml \
               -f examples/hello-world/compose.yaml up -d

# 3. Wait for the API
until curl -fsS http://localhost:8000/readyz > /dev/null; do sleep 2; done

# 4. Run atrium + host migrations
docker compose -f docker-compose.yml -f docker-compose.dev.yml \
               -f examples/hello-world/compose.yaml \
               exec api alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.dev.yml \
               -f examples/hello-world/compose.yaml \
               exec api alembic -c /host_app/alembic.ini upgrade head

# 5. Seed an admin and write system.host_bundle_url
docker compose ... exec api python -m app.scripts.seed_admin \
    --email admin@example.com --password 'secret' --full-name 'Admin' --super-admin
docker compose ... exec api python -m atrium_hello_world.scripts.seed_host_bundle /host/main.js
```

Open <http://localhost:5173>, log in, and you'll see the Hello World card on
the home page, a sidebar link to `/hello`, and a Hello World tab in the admin
shell. Flip the switch and the counter ticks every 30 seconds (the default
`HELLO_TICK_SECONDS`).

## Smoke test

```bash
make smoke-hello-dev    # against the dev stack (fast iteration)
make smoke-hello        # against the e2e stack (what CI runs)
```

The CI job is `hello-world-e2e` in `.github/workflows/ci.yml`; it gates
PR merge alongside the existing `e2e` job. PR-running CI sets
`HELLO_TICK_SECONDS=2` so the counter assertions land in seconds.

## Extracting it to its own repo

The whole point of the base-image model is that real host apps live in
their own repos. To extract:

1. Copy `examples/hello-world/` to a new repo as the project root.
2. Drop the dependency on atrium's source — the host backend image
   `FROM`s `ghcr.io/<org>/atrium-backend:<X.Y>` instead of building it
   locally.
3. The host frontend bundle is self-contained — it ships its own
   React, Mantine, and TanStack Query, and only reaches into atrium
   via `window.React.createElement` for the wrapper elements (see
   `frontend/src/main.tsx`). Nothing else changes.
4. Replace the relative `../../../frontend/tests-e2e/helpers` import in
   the smoke spec with a vendored copy of just the helpers you need
   (`loginAsSuperAdmin`, `loginAsUser`, `API_URL`).
5. Wire your own CI to run `make smoke-hello` against the published
   atrium-backend image.

The extension contract — `ATRIUM_HOST_MODULE`, the four registries,
the seed helper, the host alembic chain — is the surface you're coding
against. Any host app that respects it gets the same plumbing for free.
