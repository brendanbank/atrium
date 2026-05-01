---
name: atrium-bootstrap
description: Bootstrap a new host application on top of the published atrium base image, or retrofit an existing FastAPI / SQLAlchemy / React app onto atrium. Use when the user says "start a new project on atrium", "atrium scaffold", or "move my app onto atrium".
---

# Bootstrap a new project on top of atrium

Atrium ships as a Docker image (`ghcr.io/<org>/atrium:<X.Y>`). The host
project lives in its own repo, `FROM`s the atrium image, adds a backend
Python package + a frontend host bundle, and wires both in through a
narrow contract. **Never edit atrium files** — the next upgrade replaces
them.

The companion guide [`README.md`](README.md) in this directory is the
verbose reference (full file templates, retrofit playbook, gotchas). The
canonical worked example is [`../../examples/hello-world/`](../../examples/hello-world/).
This SKILL.md is the procedure to follow when an agent is doing the
bootstrap.

## Default to the scaffolder

For a vanilla host (single Python module, single frontend bundle, the
standard extension shape), **run the scaffolder rather than emitting
files by hand**:

```sh
npx @brendanbank/create-atrium-host <project-name> --yes-defaults --no-git
```

The emitted repo wires every registry slot, ships CI, and uses the
published `@brendanbank/atrium-host-*` packages — its `frontend/src/main.tsx`
is the post-foundation shape (~10 lines, no wrapper-element code). Skim
the emitted README and the demo `Welcome*` components, delete what
you don't need, and start adding your domain code.

Drop down to the manual procedure below only when the user explicitly
asks for a non-default shape (multiple host packages in one repo,
custom alembic layout, ship-your-own-SPA, retrofit of an existing
codebase).

> **Example version-pinning.** `examples/hello-world/` tracks `master`
> and exercises whatever extension surface ships at HEAD. If the user
> pins their atrium image to an older `X.Y` tag (sensible for prod),
> read the example **at the matching git tag** — `git checkout vX.Y.Z
> -- examples/hello-world/` — before copying snippets. The host
> registry tolerates calls to slots that don't exist in the running
> image (logs a console warning, the rest of the bundle continues
> registering), so a newer-than-image bundle degrades gracefully
> rather than catastrophically — but the slot still won't render.

## Up-front decisions to confirm with the user

Before writing files, confirm:

1. **Project / image name** (e.g. `bookings`). Used as the docker image
   tag and project root.
2. **Python module name** (e.g. `bookings`). Importable on PYTHONPATH;
   referenced by `ATRIUM_HOST_MODULE=<module>.bootstrap`. Must not
   collide with `app` (atrium owns it) or any pip-installed package.
3. **Atrium image pin**: `ghcr.io/<org>/atrium:<X.Y>` for patch uptake,
   `:<X.Y.Z>` for fully deterministic deploys. `:latest` is for tinker
   only — refuse it for any branch the user calls "prod".
4. **Public hostname + URL** for `APP_BASE_URL`, `WEBAUTHN_RP_ID`,
   `WEBAUTHN_ORIGIN`. Localhost is fine for local dev.
5. **Whether they're retrofitting an existing app**. If yes, ask which
   concerns atrium can take over (auth, audit, email, jobs, admin shell)
   so existing code can be deleted rather than ported.

Don't assume answers. Mismatched module names or the wrong image tag
fail late and noisily.

## Procedure

Below, `<your-app>` is the project name and `<your_pkg>` is the Python
module name. Replace both consistently.

### 1. Repo skeleton

```bash
mkdir -p <your-app>/{backend/src/<your_pkg>,backend/alembic/versions,frontend/src}
cd <your-app>
git init
```

Add a top-level `.gitignore` covering `.env`, `node_modules`, `dist/`,
`__pycache__/`, `.venv/`, `*.pyc`.

### 2. Backend host package

Create these files (full contents in [`README.md`](README.md), section
*Step 2*):

- `backend/pyproject.toml` — hatchling, name `<your-app>-host`, no
  runtime deps (atrium image provides them).
- `backend/src/<your_pkg>/__init__.py` — empty marker.
- `backend/src/<your_pkg>/bootstrap.py` — define `init_app(app:
  FastAPI) -> None` and optionally `init_worker(host: HostWorkerCtx)
  -> None` (`from app.host_sdk.worker import HostWorkerCtx`).
  `init_app` mounts your router. `init_worker` registers job
  handlers via `host.register_job_handler(kind=..., handler=...,
  description=...)` and APScheduler ticks via
  `host.scheduler.add_job(...)`. Either may be absent (atrium logs
  `host.init_app.absent`); both run loud if the module fails to import.
- `backend/src/<your_pkg>/models.py` — define `class HostBase(DeclarativeBase)`
  and your tables on it. **Never** parent host tables on `app.db.Base`.
- `backend/src/<your_pkg>/router.py` — a normal FastAPI APIRouter.
  Use `prefix="/api/<your_pkg>"` so the SPA owns un-prefixed URL
  space (atrium issue #89). Imports atrium's `current_user` (auth
  required) or `require_perm("...")` (permission required) for
  gating.

### 3. Alembic chain

- `backend/alembic.ini` — uses `%(here)s` so `script_location` resolves
  to the file's directory, not the caller's CWD.
- `backend/alembic/env.py` — copy from atrium's `backend/alembic/env.py`
  and adjust:
  - `target_metadata = HostBase.metadata` (host tables only)
  - `version_table = "alembic_version_app"` (separate from atrium's
    `alembic_version`)
  - Add `process_revision_directives=emit_host_foreign_keys` (from
    `app.host_sdk.alembic`) so cross-base FKs declared with
    `HostForeignKey` land in autogenerated migrations.
  - Add an `include_object` filter so autogenerate doesn't propose
    `drop_table` ops for atrium's tables. See `../host-models.md` for
    the boilerplate.
- `backend/alembic/versions/0001_init.py` — `op.create_table(...)` your
  domain tables, then `seed_permissions_sync(op.get_bind(), [codes],
  grants={"role": [codes]})` for permissions. `super_admin` is
  auto-granted; unknown role codes warn and skip.

### 4. Frontend host bundle

The bundle is a separate Vite project that emits one ES module
(`main.js`) atrium dynamic-imports on SPA boot. Ship its own React,
ReactDOM, Mantine, TanStack Query — atrium's React stays out of the
host subtree.

- `frontend/package.json` — react/react-dom 19, mantine 9, tanstack
  query 5, vite 8, typescript 6, tabler icons 3. Single script: `vite
  build`. **Add `vite-plugin-css-injected-by-js` as a devDependency** —
  see vite.config.ts below.
- `frontend/vite.config.ts` — library mode (`build.lib`), single
  output `main.js`, define `process.env.NODE_ENV` and `process.env`
  so React/TanStack don't throw on a missing process shim. **Plug
  `vite-plugin-css-injected-by-js` into `plugins`**: Vite's lib build
  extracts every `import 'pkg/styles.css'` into a sibling
  `<bundle-name>.css`, but atrium dynamic-imports `main.js` only —
  the sibling never loads and the page renders unstyled. The plugin
  rewrites those imports to inject CSS via a runtime `<style>` tag,
  so a single `main.js` carries everything. Add it preemptively even
  if the bundle has no CSS imports today: the failure mode (silently
  unstyled widgets) is annoying to diagnose later.
- `frontend/src/main.tsx` — the entry. Reads `window.React` and
  `window.__ATRIUM_REGISTRY__` (both set by atrium's main.tsx before
  the dynamic import). Calls `reg.register{HomeWidget,Route,NavItem,AdminTab,ProfileItem}`.
- `frontend/src/api.ts` — plain fetch with `credentials: 'include'` so
  the atrium auth cookie is sent. Default base URL `/api`.
- `frontend/src/queryClient.ts` — a single `new QueryClient(...)`
  shared across every component the bundle registers.
- One `<Component>.tsx` per slot — each wraps its tree in
  `<MantineProvider>` + `<QueryClientProvider client={queryClient}>`.

### 5. Two-React-trees pattern

The wrapper is mandatory:

```tsx
const AtriumReact = (window as unknown as { React?: { createElement: (...a: unknown[]) => unknown } }).React;
type MountedEl = HTMLElement & { __hostRoot?: Root };

function mountInside(el: HTMLElement | null, child: React.ReactElement): void {
  if (!el) return;
  const slot = el as MountedEl;
  if (slot.__hostRoot) return;
  slot.__hostRoot = createRoot(slot);
  slot.__hostRoot.render(child);
}

function makeWrapperElement(child: React.ReactElement): unknown {
  return AtriumReact!.createElement('div', {
    ref: (el: HTMLElement | null) => mountInside(el, child),
  });
}

reg.registerHomeWidget({
  key: 'your-widget',
  render: () => makeWrapperElement(<YourWidget />),
});
```

Atrium's React creates the wrapper `<div>`; the bundle's `createRoot`
mounts inside it via the ref callback. Two reconcilers, no shared
hooks. The `__hostRoot` guard makes the ref idempotent under
StrictMode / route remounts.

Hooks-free elements (Tabler icons, plain SVG) can be passed directly to
atrium's React via `AtriumReact.createElement(IconHome, { size: 18 })`
— used for nav-item and admin-tab icons.

### 6. Dockerfile

Two-stage build: node-builder for the SPA, then `FROM ${ATRIUM_IMAGE}`
to install the host package and copy the bundle into the static dir:

```dockerfile
ARG ATRIUM_IMAGE=ghcr.io/<org>/atrium:0.23
FROM node:25-alpine AS frontend-builder
WORKDIR /app
RUN npm install -g pnpm@10.33.1
COPY frontend/package.json frontend/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile 2>/dev/null || pnpm install
COPY frontend/ ./
ARG VITE_API_BASE_URL="/api"
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN pnpm build

FROM ${ATRIUM_IMAGE} AS runtime
USER root
COPY backend /opt/host_app
RUN /opt/venv/bin/python -m ensurepip --upgrade \
 && /opt/venv/bin/python -m pip install --no-cache-dir /opt/host_app
COPY --from=frontend-builder /app/dist /opt/atrium/static/host
USER app
```

### 7. docker-compose.yml

Three services: `api`, `worker`, `mysql`. Both api and worker share the
host image (the worker overrides CMD to `python -m app.worker`).
Required env vars on **both** api and worker:

- `ATRIUM_HOST_MODULE=<your_pkg>.bootstrap`
- `PYTHONPATH=/app`
- `DATABASE_URL`, `JWT_SECRET`, `APP_SECRET_KEY`, `APP_BASE_URL`
- `WEBAUTHN_RP_ID`, `WEBAUTHN_RP_NAME`, `WEBAUTHN_ORIGIN`
- `MAIL_BACKEND`, `MAIL_FROM` (and `SMTP_*` if `MAIL_BACKEND=smtp`)

Disable healthcheck on the worker (`healthcheck: { disable: true }`) —
the shared image's HEALTHCHECK curls `/api/healthz`, which the worker
has no HTTP port for.

### 8. .env.example

Copy from [`README.md`](README.md) section *Step 7* and fill secrets
with placeholders. Tell the user to generate `APP_SECRET_KEY` and
`JWT_SECRET` with `openssl rand -hex 48`. Don't commit `.env` — only
`.env.example`.

### 9. First-boot ritual

After the user confirms they've filled in `.env`:

```bash
docker compose up -d --build
docker compose exec api alembic upgrade head                         # atrium migrations
docker compose exec api alembic -c /opt/host_app/alembic.ini upgrade head   # host migrations
docker compose exec api python -m app.scripts.seed_admin \
    --email <user-email> --password <password> \
    --full-name '<Their Name>' --super-admin
```

Then write `system.host_bundle_url=/host/main.js` so atrium loads the
bundle. The simplest approach is to copy
[`examples/hello-world/backend/src/atrium_hello_world/scripts/seed_host_bundle.py`](../../examples/hello-world/backend/src/atrium_hello_world/scripts/seed_host_bundle.py)
into the host package as `<your_pkg>/scripts/seed_host_bundle.py` and
invoke:

```bash
docker compose exec api python -m <your_pkg>.scripts.seed_host_bundle /host/main.js
```

Or do it inline with the Python snippet in [`README.md`](README.md)
section *Step 8*.

### 9b. Backend tests in-container (optional)

The runtime image strips `pytest`, `pytest-asyncio`, and `httpx`. If the
host wants to run backend tests in the api container, install them on
demand or bake a `dev` Dockerfile stage. See [`README.md`](README.md)
section *Running backend tests in-container* for both patterns and a
Make target.

### 10. Verify

Open `http://localhost:8000`, log in with the seeded admin, and confirm
the registered widget(s) appear. If the bundle didn't load, check the
browser console for `[atrium] host bundle failed to load` (the SPA logs
the URL on failure). Common causes:

- `system.host_bundle_url` missing or wrong (run the seed script).
- Bundle path inside the image is wrong — should be at
  `/opt/atrium/static/host/main.js` so atrium serves it at
  `/host/main.js`.
- Bundle threw at import time — check `[your_pkg]` console errors;
  usually `window.React` was undefined, meaning the bundle script ran
  before atrium's main.tsx mounted (only happens if you `<script>`
  the bundle directly instead of going through `host_bundle_url`).

## Retrofit cadence

When the user is bringing an existing app onto atrium (the
booking-app-casa case):

1. **Stand up the empty host repo first.** Do steps 1-9 above with a
   single placeholder model + endpoint, prove the round-trip works
   (login + bundle loads + endpoint reachable).
2. **Identify what atrium replaces.** Walk the existing codebase with
   the user and tag every module as *delete* (atrium owns it) or
   *port* (domain code). Concerns atrium owns: auth, RBAC, audit,
   email pipeline, scheduled jobs, notifications, admin shell, theme,
   i18n, maintenance mode, account deletion. Don't port any of those.
3. **Port models module-by-module** onto `HostBase`. Drop any
   `users` / `roles` / `permissions` / `auth_sessions` / `email_*` /
   `audit_log` / `scheduled_jobs` / `notifications` / `app_settings`
   tables — atrium has them.
4. **Port routers**. Replace any custom auth middleware with
   `Depends(current_user)` or `Depends(require_perm("..."))`.
5. **Port migrations as a single fresh `0001_init.py`.** Don't carry
   the old chain over. Dump existing data with `mysqldump`, load it
   after `alembic upgrade head` if needed.
6. **Port frontend pages as host-bundle exports.** Drop the existing
   app shell — atrium ships header, sidebar, login, profile, admin
   tabs. Keep the domain components and call them from
   `registerRoute` / `registerNavItem` / `registerHomeWidget` /
   `registerAdminTab`.
7. **Move config into atrium's KV.** Branding, feature flags,
   translations, password policy, captcha config — move them into
   `app_settings` namespaces (existing or new via
   `register_namespace`). Anything secret stays in `.env`.

The retrofit is done when:
- Every route in the existing app either lives in
  `<your_pkg>/router.py` or has been deleted because atrium covers it.
- Every page in the existing SPA is either a host-bundle registration
  or has been deleted.
- All migrations are on the `alembic_version_app` chain; the old chain
  is gone.
- Tests pass against the new shape.

## Reference: extension surface

```python
# Backend
from app.auth.users import current_user                  # auth required
from app.auth.rbac import require_perm                   # permission required
from app.auth.rbac_seed import seed_permissions_sync     # in alembic migration
from app.auth.rbac_seed import seed_permissions          # at runtime startup
from app.db import get_session, get_session_factory      # async ORM session
from app.models.auth import User                         # User type
from app.services.audit import record as record_audit    # write audit row
from app.services.notifications import notify_user       # in-app notification + SSE
from app.services.app_config import register_namespace   # admin-tunable namespace
from app.email.sender import send_and_log, enqueue_and_log  # email pipeline
from app.host_sdk.worker import HostWorkerCtx           # init_worker(host) ctx type
from app.settings import get_settings                    # env-var settings
from app.logging import log                              # structlog logger
```

```ts
// Frontend (window.__ATRIUM_REGISTRY__)
registerHomeWidget({ key, render })
registerRoute({ key, path, element, requireAuth?, layout? })
registerNavItem({ key, label, to, icon?, condition? })
registerAdminTab({ key, label, icon?, perm?, section?, order?, render })
registerProfileItem({ key, slot?, render, condition? })
registerNotificationKind({ kind, render, title?, href? })
subscribeEvent(kind, (evt) => { /* qc.invalidateQueries(...) */ })
```

## Hard rules

- **Never edit atrium files.** Pin a tag, FROM the image, override
  through extension points only.
- **Never share `Base` between host and atrium.** Use `HostBase`.
- **Cross-base FKs use `HostForeignKey`.** Column-level
  `ForeignKey("users.id")` (or any atrium-table reference) on a
  `HostBase` model fails at mapper-init — SQLAlchemy can't resolve
  across metadata. Use `HostForeignKey("users.id", ondelete=...)`
  from `app.host_sdk.db` and wire `emit_host_foreign_keys` from
  `app.host_sdk.alembic` into the host's `alembic/env.py`. The
  `ForeignKeyConstraint` then lands in autogenerated migrations
  automatically. See `../host-models.md` for the full pattern.
- **Never use atrium's alembic version table.** Use
  `alembic_version_app`.
- **Never bake secrets into the host bundle.** It's served public.
  Authentication happens at API call time.
- **Never share React, MantineProvider, or QueryClient between atrium
  and the bundle.** Two trees. The wrapper-div pattern is non-negotiable.
- **Never reimplement what atrium already ships** (auth, RBAC, audit,
  email, jobs, notifications, admin shell, theme, i18n, maintenance,
  account deletion). If a concern lives in atrium, the host's only job
  is to call it.

## When to escalate

Stop and ask the user when:

- They want to use a different DB (atrium is hard-wired to MySQL 8 +
  aiomysql).
- They want to ship a single-page app at a domain root that's not the
  atrium SPA. The bundle pattern only handles fragments inside the
  atrium shell. A standalone SPA is a separate concern (host project
  fronts atrium's API at `/api/*` and serves its own SPA).
- They want to extend atrium's user model (e.g. add columns to
  `users`). Atrium owns that table; host columns belong on a
  per-user row in a host-side table joined by user_id.
- They want to override atrium's auth (e.g. SSO via OAuth/OIDC).
  Atrium ships fastapi-users with cookies; an SSO front-end isn't a
  host extension, it's a fork.
