# Hello World example

A minimal host extension for atrium that exercises every B1 slot kind end
to end. Doubles as the live contract for the published-image extension
model — if this stops working, [`docs/published-images.md`](../../docs/published-images.md)
is lying.

## What it demonstrates

| Atrium extension point         | How the example uses it                              |
|--------------------------------|------------------------------------------------------|
| `ATRIUM_HOST_MODULE` bootstrap | `atrium_hello_world.bootstrap.init_app/init_worker`  |
| `app.include_router`           | `/hello/state` (auth) and `/hello/toggle` (perm)     |
| `seed_permissions_sync`        | Seeds `hello.toggle` in the host alembic migration   |
| APScheduler `add_job`          | 3 s tick (2 s in tests) increments the counter inline (via `host.scheduler.add_job` on the `HostWorkerCtx`) |
| Host alembic chain             | Own `hello_state` table in `alembic_version_app`     |
| `registerHomeWidget`           | Card on the home page                                |
| `registerRoute`                | Dedicated `/hello` page                              |
| `registerNavItem`              | Sidebar link                                         |
| `registerAdminTab`             | Admin tab gated by `hello.toggle`                    |
| `registerProfileItem`          | Toggle card on `/profile`                            |
| `registerNotificationKind`     | Bell + inbox renderer for `hello.toggled`            |
| `notify_user`                  | Backend writes a `hello.toggled` notification on toggle |

## Layout

```
examples/hello-world/
  Dockerfile                     One image: node-builder for the host
                                 bundle + FROM ghcr.io/.../atrium +
                                 pip install host pkg + COPY dist
  compose.yaml                   Self-contained prod compose
                                 (atrium-from-GHCR + host extension built
                                  on top, plain HTTP on :8000, no overlays)
  .env.example                   Copy to .env and fill in secrets
  backend/                       Host backend Python package
    pyproject.toml               (atrium-hello-world)
    src/atrium_hello_world/      bootstrap, models, router, schedule,
                                 scripts/seed_host_bundle
    alembic/                     Host alembic chain (alembic_version_app)
  frontend/                      Vite library project that emits a single
                                 ES module loaded by atrium dynamically
  host-bundle/                   Sidecar nginx config used in the dev
                                 overlay (Vite dev server can't serve the
                                 prebuilt bundle cleanly, so we serve it
                                 from a separate container in dev)
  tests-e2e/                     Playwright smoke spec (lives under
                                 frontend/tests-e2e/)
  dev/                           Dev-loop overlays (hot reload,
                                 bind-mounts, fast tick, sidecar bundle)
    compose.dev.yaml             Layers on the root atrium dev stack
```

## Running it as a demo

One self-contained compose file. No overlays.

```bash
cd examples/hello-world
cp .env.example .env                                # fill in JWT_SECRET, DB password
docker compose up -d --build                        # builds the host image, brings up mysql + api + worker
docker compose exec api alembic upgrade head        # atrium migrations
docker compose exec api alembic -c /opt/host_app/alembic.ini upgrade head   # host migrations
docker compose exec api python -m app.scripts.seed_admin \
    --email admin@example.com --password 'secret' \
    --full-name 'Admin' --super-admin
docker compose exec api python -m atrium_hello_world.scripts.seed_host_bundle /host/main.js
```

Open <http://localhost:8000>, log in, and the Hello World card appears on
the home page, alongside a sidebar link to `/hello` and a Hello World tab in
the admin shell. Flip the toggle and the counter ticks every 30 seconds (the
default `HELLO_TICK_SECONDS`). The example increments the counter inline from
the APScheduler tick — for jobs that need durability across worker restarts,
use atrium's `scheduled_jobs` queue + `host.register_job_handler(...)` from
`init_worker(host)` instead.

That's it for the demo path. No proxy, no `-f` chains, no separate frontend
container — atrium serves the SPA itself from the api process via Starlette
StaticFiles, and the host bundle is baked into the same image at
`/opt/atrium/static/host/main.js`. Put your own TLS terminator (Caddy,
nginx, your edge load balancer) in front of `:8000` for production.

## Pinning the atrium version

The compose file reads `ATRIUM_IMAGE` from `.env` (default
`ghcr.io/brendan-bank/atrium:latest`). Override to test against a specific
release:

```bash
ATRIUM_IMAGE=ghcr.io/brendan-bank/atrium:0.10.0 docker compose up -d --build
```

## Smoke test

```bash
make smoke-hello        # builds the unified image locally, runs the spec
make smoke-hello-ghcr   # same flow but pulls atrium from GHCR
```

The CI job is `hello-world-e2e` in `.github/workflows/ci.yml`; it gates PR
merge alongside the existing `e2e` job. CI sets `HELLO_TICK_SECONDS=2` so
the counter assertions land in seconds rather than minutes.

## Development (hot-reload)

For iterating on the host backend code with uvicorn `--reload` and the host
frontend with Vite HMR, layer the dev overlay on the root atrium dev stack.
This bind-mounts `examples/hello-world/backend` into the api/worker
containers and runs a sidecar nginx for the host bundle on `:5174` (Vite's
dev server can't serve the prebuilt module cleanly).

```bash
# From repo root
cd examples/hello-world/frontend && pnpm install && pnpm build && cd ../../..
docker compose -f docker-compose.yml \
               -f docker-compose.dev.yml \
               -f examples/hello-world/dev/compose.dev.yaml up -d
docker compose ... exec api alembic upgrade head
docker compose ... exec api alembic -c /host_app/alembic.ini upgrade head
docker compose ... exec api python -m atrium_hello_world.scripts.seed_host_bundle \
    http://localhost:5174/main.js
```

`make smoke-hello-dev` runs all of the above plus the Playwright spec and
leaves the stack up.

## Extracting it to its own repo

The whole point of the base-image model is that real host apps live in
their own repos. To extract:

1. Copy `examples/hello-world/` to a new repo as the project root.
2. The `Dockerfile` already `FROM`s `ghcr.io/<org>/atrium:<X.Y>` — pin
   to your target release.
3. The host frontend bundle is self-contained — it ships its own
   React, Mantine, and TanStack Query, and only reaches into atrium
   via `window.React.createElement` for the wrapper elements (see
   `frontend/src/main.tsx`). Nothing else changes.
4. Replace the spec's import of helpers with a vendored copy of just
   the helpers you need (`loginAsSuperAdmin`, `loginAsUser`, `API_URL`).
5. Wire your own CI to run `docker compose build && docker compose up -d`
   + the Playwright spec against the published atrium image.

The extension contract — `ATRIUM_HOST_MODULE`, the four registries,
the seed helper, the host alembic chain — is the surface you're coding
against. Any host app that respects it gets the same plumbing for free.
