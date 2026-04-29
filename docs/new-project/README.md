# Starting a new project on top of atrium

Atrium is consumed as a **base Docker image**. Your application lives in
its own repo, `FROM`s the published atrium image, adds a backend Python
package and a frontend host bundle, and wires both into atrium through a
narrow extension contract — no atrium files are edited.

## The fast path: scaffolder

For a vanilla host (one Python module, one frontend bundle, the
default extension shape), the recommended on-ramp is the scaffolder:

```sh
npx @brendanbank/create-atrium-host casa-del-leone
cd casa-del-leone
cp .env.example .env                   # fill in secrets
make dev-bootstrap
make seed-admin EMAIL=you@example.com PASSWORD='good-password'
make seed-bundle
open http://localhost:8000
```

The emitted repo is git-initialised, has CI wired
(`.github/workflows/ci.yml` + `dependabot.yml`), pulls the published
`@brendanbank/atrium-host-{types,bundle-utils,test-utils}` packages,
and ships a worked example for every registry slot — home widget,
route, nav item, admin tab, profile-page card. `make test` is green
out of the box once the packages are reachable.

Run `npx @brendanbank/create-atrium-host --help` for the flag list
(`--yes-defaults`, `--no-git`, `--out`, `--atrium`).

## The custom path: this guide

The rest of this document is the verbose, hand-rolled walkthrough.
Use it when:

- You need a non-vanilla shape (multiple host packages in one repo,
  custom alembic chain layout, no Mantine, ship-your-own-SPA-at-root).
- You're retrofitting an existing FastAPI / SQLAlchemy / React app
  rather than starting blank — see *Retrofitting an existing app*
  below.
- You want to read every file before agreeing to it (the scaffolder
  emits ~34 files; this guide is what each of them does).

The contract surface (image catalogue, tagging, registries) is in
[`../published-images.md`](../published-images.md); the canonical worked
example is [`../../examples/hello-world/`](../../examples/hello-world/),
which exercises every extension slot end to end.

For the AI-driven bootstrap version, see [`SKILL.md`](SKILL.md) in the
same directory.

## What you're building

```
+----------------------------------------+
|  ghcr.io/<org>/atrium:X.Y              |  base image
|  - FastAPI app (auth/RBAC/audit/...)   |
|  - APScheduler worker                  |
|  - SPA shell (served from /opt/...)    |
+----------------------------------------+
                ^
                | FROM, plus:
                |
+----------------------------------------+
|  your-app:1.0.0                        |  one image, two roles
|  - pip install ./backend  (host pkg)   |
|  - host bundle at /opt/.../host/main.js|
+----------------------------------------+
```

One Docker image. Two services off it: api (FastAPI + SPA) and worker
(APScheduler). Atrium loads your host module via `ATRIUM_HOST_MODULE`,
your alembic chain runs on its own version table, your SPA bundle is
dynamic-imported by atrium's SPA on boot.

## Prerequisites

- Docker with Compose v2.
- Node 25+ and pnpm 10+ if you want to build the host bundle on the host
  (otherwise the Dockerfile builds it inside `node:25-alpine`).
- Python 3.12+ if you want to run host backend tests on the host.
- A pinned atrium tag: pick `X.Y` (auto-uptake patch releases) or
  `X.Y.Z` (fully deterministic). `latest` is for tinkering only.

## Minimum repo layout

```
your-app/
  Dockerfile                 # FROM atrium, install host pkg, copy bundle
  docker-compose.yml         # api + worker + mysql
  .env.example               # APP_SECRET_KEY, JWT_SECRET, DSN, ATRIUM_HOST_MODULE...

  backend/
    pyproject.toml           # name = "your-app-host"
    alembic.ini              # script_location, prepend_sys_path
    src/
      your_app/
        __init__.py
        bootstrap.py         # init_app(app), init_worker(host)
        models.py            # HostBase = DeclarativeBase()
        router.py            # APIRouter mounted by init_app
    alembic/
      env.py                 # version_table = "alembic_version_app"
      versions/
        0001_init.py         # create_table + seed_permissions_sync

  frontend/
    package.json
    vite.config.ts           # lib mode, single main.js output
    tsconfig.json
    src/
      main.tsx               # window.__ATRIUM_REGISTRY__.register*
      api.ts
      queryClient.ts
      <YourWidget>.tsx
```

That's the skeleton. Everything else (tests, CI, multiple migrations,
more pages) is incremental on top.

## Step 1 - Pick a host package name

Pick something unique that won't clash with atrium's own modules. Atrium
owns the `app.*` namespace; pick anything else. The hello-world example
uses `atrium_hello_world`; for a bookings app you might use
`booking_app_host` or just `bookings`.

Throughout this doc, `<your_pkg>` is the Python module name (e.g.
`bookings`) and `<your-app>` is the project / image name (e.g.
`bookings`).

## Step 2 - Backend host package

### `backend/pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "<your-app>-host"
version = "0.1.0"
requires-python = ">=3.12"

# Runtime deps come from the atrium image (FastAPI, SQLAlchemy, Alembic,
# structlog). Listing them here would just shadow atrium's pinned
# versions. The package is installed via `pip install ./backend` inside
# the runtime image so `<your_pkg>` is importable on PYTHONPATH.

[tool.hatch.build.targets.wheel]
packages = ["src/<your_pkg>"]
```

### `backend/src/<your_pkg>/__init__.py`

Empty. Marker file.

### `backend/src/<your_pkg>/bootstrap.py`

The two entry points atrium calls when `ATRIUM_HOST_MODULE` points at
this module:

```python
from __future__ import annotations
from fastapi import FastAPI

from app.host_sdk.worker import HostWorkerCtx


def init_app(app: FastAPI) -> None:
    """Called once during create_app(), after every atrium router is
    included and before the SPA static mount + ASGI start."""
    from .router import router
    app.include_router(router)
    # Optional: register an app_settings namespace.
    # from app.services.app_config import register_namespace
    # from .config import YourConfig
    # register_namespace("your_ns", YourConfig, public=False)


def init_worker(host: HostWorkerCtx) -> None:
    """Called on worker startup, after register_builtin_handlers() and
    before scheduler.start()."""
    # Recurring APScheduler tick:
    # from .schedule import tick
    # host.scheduler.add_job(tick, "interval", seconds=30,
    #                        id="your-tick", coalesce=True, max_instances=1)
    #
    # Durable scheduled_jobs handler:
    # from .handlers import handle_thing
    # host.register_job_handler(
    #     kind="your_kind",
    #     handler=handle_thing,
    #     description="Drain your_kind scheduled_jobs rows",
    # )
    pass
```

Both functions are optional. A module that defines neither is allowed —
import side-effects alone are fine. Atrium logs `host.init_app.absent` /
`host.init_worker.absent` if they're missing.

If `ATRIUM_HOST_MODULE` is set but the module doesn't import, atrium
fails startup loudly. The operator opted in; a typo should not silently
launch atrium without the host.

### `backend/src/<your_pkg>/models.py`

```python
from __future__ import annotations
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, Integer, String, text
from sqlalchemy.dialects.mysql import DATETIME as MysqlDATETIME
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class HostBase(DeclarativeBase):
    """Host metadata, separate from atrium's `app.db.Base`.

    Keeps autogenerate honest — alembic only sees host tables, never
    atrium's. The two chains share the database, but their version
    tables (`alembic_version` for atrium, `alembic_version_app` for
    the host) advance independently.
    """


class YourThing(HostBase):
    __tablename__ = "your_thing"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        MysqlDATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
```

**Never** mix host tables into `app.db.Base`. The next atrium upgrade
may collide with whatever you added.

#### Referencing atrium tables from host models

Host models live on `HostBase`, which has its own `MetaData` separate
from atrium's `app.db.Base`. SQLAlchemy resolves `ForeignKey("users.id")`
within a single `MetaData`, so a column-level `ForeignKey()` pointing at
an atrium table (`users`, `roles`, `user_invites`, ...) cannot resolve
and will fail at mapper configuration. Sharing `Base` to "fix" it would
break alembic autogenerate isolation — don't.

Use `HostForeignKey` from `app.host_sdk.db` and wire
`emit_host_foreign_keys` into the host's `alembic/env.py`:

```python
from sqlalchemy import BigInteger, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.host_sdk.db import HostForeignKey


class Booking(HostBase):
    __tablename__ = "bookings"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        HostForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
```

```python
# backend/alembic/env.py — additions only
from app.host_sdk.alembic import emit_host_foreign_keys

def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        process_revision_directives=emit_host_foreign_keys,
    )
    ...
```

`alembic revision --autogenerate` will then emit a migration whose
`create_table` op contains an `sa.ForeignKeyConstraint(["user_id"],
["users.id"], ondelete="CASCADE")`. The mapper still doesn't see a
column-level FK — the helper is a no-op as far as ORM mapping is
concerned, it just stamps a marker the alembic hook reads at
autogenerate time.

`relationship()` from a `HostBase` model toward an atrium model still
doesn't work — there's no ORM-level FK to follow. When you need the
atrium row, load it explicitly:

```python
from app.models.auth import User

user = await session.get(User, booking.user_id)
```

See [`../host-models.md`](../host-models.md) for the full rationale,
the `include_object` filter every host env.py needs to keep
autogenerate from proposing `drop_table` ops on atrium's tables, and
`HostForeignKey` corner cases.

### `backend/src/<your_pkg>/router.py`

A normal FastAPI router. Atrium auth dependencies are imported from
`app.*`:

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import require_perm
from app.auth.users import current_user
from app.db import get_session
from app.models.auth import User
from app.services.audit import record as record_audit

router = APIRouter(prefix="/your-thing", tags=["your-thing"])


class ThingOut(BaseModel):
    id: int
    name: str


@router.get("/{thing_id}", response_model=ThingOut)
async def get_thing(
    thing_id: int,
    _user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ThingOut:
    ...


@router.post("/{thing_id}/toggle")
async def toggle(
    thing_id: int,
    user: User = Depends(require_perm("your_thing.toggle")),
    session: AsyncSession = Depends(get_session),
) -> ThingOut:
    ...
    await record_audit(
        session,
        actor_user_id=user.id,
        entity="your_thing",
        entity_id=thing_id,
        action="toggle",
        diff={...},
    )
    await session.commit()
    ...
```

## Step 3 - Alembic chain

### `backend/alembic.ini`

```ini
[alembic]
script_location = %(here)s/alembic
prepend_sys_path = %(here)s/src

[loggers]
keys = root, sqlalchemy, alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

`%(here)s` resolves to the INI file's directory, not the caller's CWD.
This matters because alembic will be invoked as `alembic -c
/opt/host_app/alembic.ini upgrade head` from inside the api container,
where the CWD is `/app` (atrium's source). Without `%(here)s`, alembic
would try to load atrium's chain from the wrong directory.

### `backend/alembic/env.py`

The two changes from atrium's `env.py`:

```python
from __future__ import annotations
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Imports the model module so HostBase.metadata is populated before
# autogenerate runs.
import <your_pkg>.models  # noqa: F401
from alembic import context
from app.settings import get_settings
from <your_pkg>.models import HostBase

# THE first key change - separate version table.
VERSION_TABLE = "alembic_version_app"

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

if not config.get_main_option("sqlalchemy.url") or config.get_main_option(
    "sqlalchemy.url"
).startswith("driver://"):
    config.set_main_option("sqlalchemy.url", get_settings().database_url)

# THE second key change - host metadata only.
target_metadata = HostBase.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url, target_metadata=target_metadata,
        literal_binds=True, dialect_opts={"paramstyle": "named"},
        version_table=VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        compare_type=True, render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

The two load-bearing lines: `target_metadata = HostBase.metadata` and
`version_table = "alembic_version_app"`. Drop either and your chain
collides with atrium's.

### `backend/alembic/versions/0001_init.py`

```python
from __future__ import annotations
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.auth.rbac_seed import seed_permissions_sync
from sqlalchemy.dialects.mysql import DATETIME as MysqlDATETIME

revision: str = "0001_init"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "your_thing",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", MysqlDATETIME(fsp=6), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
    )

    # Permissions belong with the schema. The runtime form
    # (`seed_permissions`) exists for hosts that discover permissions
    # at startup; for static codes, the migration form is the natural
    # fit. Atrium auto-grants every seeded permission to super_admin;
    # `grants` adds extra role bindings.
    seed_permissions_sync(
        op.get_bind(),
        ["your_thing.toggle", "your_thing.read"],
        grants={"admin": ["your_thing.toggle"]},
    )


def downgrade() -> None:
    # Permissions intentionally left in place on downgrade — they're
    # cheap to keep and removing them would orphan any UI still
    # referencing the code.
    op.drop_table("your_thing")
```

## Step 4 - Frontend host bundle

The bundle is a separate Vite project that emits a single ES module
(`main.js`). Atrium dynamic-imports it on SPA boot. The bundle ships its
own React, ReactDOM, Mantine, and TanStack Query — atrium's React stays
out of the host subtree.

### `frontend/package.json`

```json
{
  "name": "<your-app>-host-bundle",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "build": "vite build",
    "build:watch": "vite build --watch",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "@mantine/core": "^9.1.0",
    "@mantine/hooks": "^9.1.0",
    "@tabler/icons-react": "^3.41.1",
    "@tanstack/react-query": "^5.100.1",
    "react": "^19.2.5",
    "react-dom": "^19.2.5"
  },
  "devDependencies": {
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "typescript": "^6.0.3",
    "vite": "^8.0.10",
    "vite-plugin-css-injected-by-js": "^3.5.2"
  }
}
```

### `frontend/vite.config.ts`

```ts
import { resolve } from 'node:path';
import { defineConfig } from 'vite';
import cssInjectedByJsPlugin from 'vite-plugin-css-injected-by-js';

export default defineConfig({
  define: {
    // React/TanStack internals read process.env.NODE_ENV at module
    // load. Defining it as a literal sidesteps the missing-process
    // shim and emits a single non-debug build.
    'process.env.NODE_ENV': JSON.stringify('production'),
    'process.env': '{}',
  },
  // Vite's lib build extracts every imported `.css` to a sibling
  // file. atrium dynamic-imports `main.js` only, so a sibling
  // `<bundle-name>.css` would sit there orphaned and the bundle would
  // render unstyled. The plugin rewrites those imports to inject the
  // CSS via a runtime `<style>` tag — a single `main.js` carries
  // everything. Keep the plugin in even when the bundle has no CSS
  // imports today: the failure mode (silently unstyled widgets the
  // first time you `import 'fullcalendar/main.css'`) is unpleasant
  // to diagnose.
  plugins: [cssInjectedByJsPlugin()],
  build: {
    target: 'es2022',
    lib: {
      entry: resolve(__dirname, 'src/main.tsx'),
      formats: ['es'],
      fileName: () => 'main.js',
    },
    emptyOutDir: true,
    sourcemap: true,
  },
});
```

Library mode, not app mode. One file out: `dist/main.js`.

### `frontend/src/main.tsx`

The entry. Two React trees coexist after this file runs:

- atrium's React owns the shell + the wrapper `<div>` we hand it.
- this bundle's React owns the subtree mounted inside the wrapper.

```tsx
import { createRoot, type Root } from 'react-dom/client';
import { IconHome } from '@tabler/icons-react';

import { YourPage } from './YourPage';
import { YourWidget } from './YourWidget';

interface AtriumRegistry {
  registerHomeWidget: (w: { key: string; render: () => unknown }) => void;
  registerRoute: (r: {
    key: string; path: string; element: unknown;
    requireAuth?: boolean; layout?: 'shell' | 'bare';
  }) => void;
  registerNavItem: (n: {
    key: string; label: string; to: string; icon?: unknown;
  }) => void;
  registerAdminTab: (t: {
    key: string; label: string; icon?: unknown;
    perm?: string; element: unknown;
  }) => void;
  registerProfileItem: (p: {
    key: string;
    slot?:
      | 'after-profile' | 'after-password' | 'after-2fa'
      | 'after-roles' | 'after-sessions' | 'before-delete';
    render: () => unknown;
  }) => void;
  registerNotificationKind: (r: {
    kind: string;
    render: (n: {
      id: number; kind: string; payload: Record<string, unknown>;
      read_at: string | null; created_at: string;
    }) => unknown;
    title?: (n: { kind: string; payload: Record<string, unknown> }) => string;
    href?: (n: { kind: string; payload: Record<string, unknown> }) => string;
  }) => void;
  subscribeEvent: (
    kind: string,
    handler: (event: { kind: string; payload: Record<string, unknown> }) => void,
  ) => () => void;
}

const AtriumReact = (
  window as unknown as { React?: { createElement: (...a: unknown[]) => unknown } }
).React;

if (!AtriumReact) {
  console.error('[<your_pkg>] window.React missing — atrium SPA must mount before host bundle loads');
}

type MountedEl = HTMLElement & { __hostRoot?: Root };

function mountInside(el: HTMLElement | null, child: React.ReactElement): void {
  if (!el) return;
  const slot = el as MountedEl;
  if (slot.__hostRoot) return;  // re-runs (StrictMode, route remount) are no-ops
  slot.__hostRoot = createRoot(slot);
  slot.__hostRoot.render(child);
}

function makeWrapperElement(child: React.ReactElement): unknown {
  // atrium's React creates the wrapper div; our React mounts inside it
  // when atrium commits the div to the DOM.
  return AtriumReact!.createElement('div', {
    ref: (el: HTMLElement | null) => mountInside(el, child),
  });
}

const reg = (window as unknown as { __ATRIUM_REGISTRY__?: AtriumRegistry })
  .__ATRIUM_REGISTRY__;

if (reg && AtriumReact) {
  reg.registerHomeWidget({
    key: 'your-widget',
    render: () => makeWrapperElement(<YourWidget />),
  });
  reg.registerRoute({
    key: 'your-page',
    path: '/your',
    element: makeWrapperElement(<YourPage />),
  });
  reg.registerNavItem({
    key: 'your-nav',
    label: 'Your Thing',
    to: '/your',
    // Hooks-free icons (plain SVG output) can be passed directly.
    icon: AtriumReact.createElement(IconHome, { size: 18 }),
  });
}
```

### `frontend/src/api.ts`

Plain fetch (no axios import — keep the bundle small):

```ts
const apiBase =
  (import.meta as { env?: { VITE_API_BASE_URL?: string } }).env?.VITE_API_BASE_URL ??
  '/api';

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`api ${res.status}: ${body}`);
  }
  return (await res.json()) as T;
}

export interface YourThing {
  id: number;
  name: string;
}

export async function getThing(id: number): Promise<YourThing> {
  const res = await fetch(`${apiBase}/your-thing/${id}`, {
    credentials: 'include',
    headers: { Accept: 'application/json' },
  });
  return jsonOrThrow<YourThing>(res);
}
```

`credentials: 'include'` carries the atrium auth cookie. Build with
`VITE_API_BASE_URL=""` (the default in the Dockerfile below) so the
bundle calls relative paths.

### `frontend/src/queryClient.ts`

A single QueryClient shared across every component the bundle registers
so they share cache for the same keys:

```ts
import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 2_000, refetchInterval: 5_000, retry: 1 },
  },
});
```

Each component this bundle exports must wrap its tree in
`<MantineProvider>` + `<QueryClientProvider client={queryClient}>` so
the host React owns its own contexts (atrium's providers don't reach
into the wrapper).

## Step 5 - Dockerfile

```dockerfile
ARG ATRIUM_IMAGE=ghcr.io/<org>/atrium:0.14

# ---- frontend-builder ----
FROM node:25-alpine AS frontend-builder
WORKDIR /app
RUN npm install -g pnpm@10.33.1
COPY frontend/package.json frontend/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile 2>/dev/null || pnpm install
COPY frontend/ ./
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN pnpm build

# ---- runtime ----
FROM ${ATRIUM_IMAGE} AS runtime

USER root
COPY backend /opt/host_app
# atrium's runtime uses uv to build the venv but doesn't install pip
# into it. ensurepip bootstraps pip so we can install our package.
RUN /opt/venv/bin/python -m ensurepip --upgrade \
 && /opt/venv/bin/python -m pip install --no-cache-dir /opt/host_app

# Bundle lands at /opt/atrium/static/host/main.js. atrium serves
# /opt/atrium/static at the SPA's root, so the file becomes
# /host/main.js — set system.host_bundle_url=/host/main.js to load it.
COPY --from=frontend-builder /app/dist /opt/atrium/static/host

USER app
```

## Step 6 - docker-compose.yml

```yaml
services:
  api:
    build:
      context: .
      dockerfile: Dockerfile
      args:
        ATRIUM_IMAGE: ${ATRIUM_IMAGE:-ghcr.io/<org>/atrium:1}
    image: <your-app>:latest
    pull_policy: never
    restart: unless-stopped
    environment:
      ENVIRONMENT: ${ENVIRONMENT:-prod}
      APP_TIMEZONE: ${APP_TIMEZONE:-UTC}
      APP_SECRET_KEY: ${APP_SECRET_KEY}
      APP_BASE_URL: ${APP_BASE_URL}
      DATABASE_URL: ${DATABASE_URL}
      JWT_SECRET: ${JWT_SECRET}
      JWT_ACCESS_TOKEN_EXPIRE_MINUTES: ${JWT_ACCESS_TOKEN_EXPIRE_MINUTES:-10080}
      WEBAUTHN_RP_ID: ${WEBAUTHN_RP_ID}
      WEBAUTHN_RP_NAME: ${WEBAUTHN_RP_NAME}
      WEBAUTHN_ORIGIN: ${WEBAUTHN_ORIGIN}
      MAIL_BACKEND: ${MAIL_BACKEND:-console}
      MAIL_FROM: ${MAIL_FROM:-no-reply@example.com}
      ATRIUM_HOST_MODULE: <your_pkg>.bootstrap
      # Host alembic runs with cwd=/opt/host_app and its env.py imports
      # `app.settings`. atrium's source is at /app — put it on PYTHONPATH
      # so the import resolves regardless of CWD.
      PYTHONPATH: /app
    ports:
      - "8000:8000"
    depends_on:
      mysql:
        condition: service_healthy

  worker:
    image: <your-app>:latest
    pull_policy: never
    restart: unless-stopped
    environment:
      ENVIRONMENT: ${ENVIRONMENT:-prod}
      APP_TIMEZONE: ${APP_TIMEZONE:-UTC}
      APP_SECRET_KEY: ${APP_SECRET_KEY}
      APP_BASE_URL: ${APP_BASE_URL}
      DATABASE_URL: ${DATABASE_URL}
      JWT_SECRET: ${JWT_SECRET}
      MAIL_BACKEND: ${MAIL_BACKEND:-console}
      MAIL_FROM: ${MAIL_FROM:-no-reply@example.com}
      ATRIUM_HOST_MODULE: <your_pkg>.bootstrap
      PYTHONPATH: /app
    command: ["python", "-m", "app.worker"]
    depends_on:
      mysql:
        condition: service_healthy
      api:
        condition: service_started
    # The shared image's HEALTHCHECK curls /healthz, which the worker
    # has no HTTP port for. Disable it.
    healthcheck:
      disable: true

  mysql:
    image: mysql:8.0
    restart: unless-stopped
    command: --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci --default-time-zone=+00:00
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
      MYSQL_DATABASE: ${MYSQL_DATABASE}
      MYSQL_USER: ${MYSQL_USER}
      MYSQL_PASSWORD: ${MYSQL_PASSWORD}
    volumes:
      - mysql_data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-u", "root", "-p${MYSQL_ROOT_PASSWORD}"]
      interval: 10s
      timeout: 5s
      retries: 10

volumes:
  mysql_data:
    name: <your-app>_mysql_data
```

Add an edge proxy (Caddy, nginx, your VM's terminator) in front of
`:8000` for TLS in production. Atrium speaks plain HTTP by design.

## Step 7 - .env.example

```bash
ENVIRONMENT=prod
APP_TIMEZONE=UTC

# Long random strings. `openssl rand -hex 48` for each.
APP_SECRET_KEY=
JWT_SECRET=
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=10080

# The public URL the browser hits. Used in email links.
APP_BASE_URL=https://app.example.com

# MySQL.
MYSQL_ROOT_PASSWORD=
MYSQL_DATABASE=app
MYSQL_USER=app
MYSQL_PASSWORD=
DATABASE_URL=mysql+aiomysql://${MYSQL_USER}:${MYSQL_PASSWORD}@mysql:3306/${MYSQL_DATABASE}

# WebAuthn — the host the credential is bound to (no scheme/port) and
# the full origin the registration ceremony runs from.
WEBAUTHN_RP_ID=app.example.com
WEBAUTHN_RP_NAME=Your App
WEBAUTHN_ORIGIN=https://app.example.com

# Mail. `console` prints to stdout; switch to `smtp` and fill the SMTP_*
# vars in prod.
MAIL_BACKEND=console
MAIL_FROM=no-reply@example.com

# Pin the atrium base image. X.Y for patch uptake; X.Y.Z for fully
# deterministic deploys.
ATRIUM_IMAGE=ghcr.io/<org>/atrium:0.14
```

For the full env-var surface (CAPTCHA secret, SMTP host/port/user, etc.)
see `.env.example` in the atrium repo and `published-images.md` ->
*Operational notes*.

## Step 8 - First boot

From the new project's repo root:

```bash
cp .env.example .env  # fill in real secrets, public URL, DB password
docker compose up -d --build

# Atrium tables (auth, RBAC, audit, app_settings, ...).
docker compose exec api alembic upgrade head

# Host tables, on the alembic_version_app chain.
docker compose exec api alembic -c /opt/host_app/alembic.ini upgrade head

# Seed a super_admin so you can log in and configure the rest from the
# UI. Pre-enrol TOTP if you want — totp_secret is the base32 from your
# authenticator app.
docker compose exec api python -m app.scripts.seed_admin \
    --email you@example.com --password 'a-good-password' \
    --full-name 'Your Name' --super-admin

# Tell atrium where the host bundle lives. /host/main.js is the path
# atrium serves from /opt/atrium/static/host/main.js. The cleanest
# approach is to copy the hello-world helper into your package once:
#   cp ../atrium/examples/hello-world/backend/src/atrium_hello_world/scripts/seed_host_bundle.py \
#      backend/src/<your_pkg>/scripts/seed_host_bundle.py
# (and add a scripts/__init__.py marker) — then:
docker compose exec api python -m <your_pkg>.scripts.seed_host_bundle /host/main.js
```

The script is idempotent: it JSON-merges `host_bundle_url` onto whatever
already lives in `app_settings[system]`, so re-running doesn't wipe other
fields. See
[`seed_host_bundle.py`](../../examples/hello-world/backend/src/atrium_hello_world/scripts/seed_host_bundle.py)
for the source.

Open `http://localhost:8000`, log in, and your widget appears on the
home page. The host bundle is dynamic-imported on every fresh page
load; the next deploy picks up the new bundle automatically.

## Step 9 - Inner loop

Adding an endpoint, a job, a UI fragment — the standard moves:

| You want to add               | Where it lives                                           | Wire it via                                                                |
|-------------------------------|----------------------------------------------------------|----------------------------------------------------------------------------|
| HTTP endpoint                 | `<your_pkg>/router.py`                                   | `app.include_router(router)` in `init_app`                                 |
| New permission                | A new alembic migration                                  | `seed_permissions_sync(op.get_bind(), [...], grants={...})`                |
| Recurring tick                | `<your_pkg>/schedule.py` async function                  | `host.scheduler.add_job(fn, "interval", seconds=N, ...)` in `init_worker`  |
| Durable async job             | A handler `(session, job, payload) -> None`              | `host.register_job_handler(kind="...", handler=..., description="...")` in `init_worker` |
| Admin-tunable flag            | A Pydantic `BaseModel` config class                      | `register_namespace("ns", Model, public=False)` in `init_app`              |
| Per-user notification         | Inside the txn that mutated the row                      | `from app.services.notifications import notify_user`                       |
| Outbound email (queued)       | A template row in `email_templates` + a callsite         | `from app.email.sender import enqueue_and_log`                             |
| Synchronous email             | Same template; for password-reset-style flows            | `from app.email.sender import send_and_log`                                |
| Audit row                     | Inside the txn that mutated the row                      | `from app.services.audit import record`                                    |
| Home widget                   | A React component in `frontend/src/`                     | `reg.registerHomeWidget({ key, render })`                                  |
| Dedicated route               | A page component                                         | `reg.registerRoute({ key, path, element, layout? })`                       |
| Sidebar link                  | A label + path                                           | `reg.registerNavItem({ key, label, to, icon?, condition? })`               |
| Admin tab                     | A component, gated by a permission                       | `reg.registerAdminTab({ key, label, icon?, perm, element })`               |
| Profile-page card             | A component                                              | `reg.registerProfileItem({ key, slot?, render, condition? })`              |
| Bell / inbox per-kind UI      | Title + (optional) detail-modal element                  | `reg.registerNotificationKind({ kind, render, title?, href? })`            |
| Selective React Query refresh | Handler that invalidates the host's affected query keys  | `reg.subscribeEvent('your.kind', (evt) => qc.invalidateQueries({...}))`    |

Permission gating on the API: `Depends(require_perm("your_thing.read"))`.

Permission gating on the SPA: pass `perm:` to `registerAdminTab`, or
read `me.permissions` directly in your component (your bundle can fetch
`/users/me/context` itself).

### Running backend tests in-container

The published atrium image is a runtime image — `pytest`, `pytest-asyncio`,
and `httpx` are not installed. Two paths:

**Inline install + run** (good for one-off runs, no Dockerfile churn):

```bash
docker compose exec -u root api /opt/venv/bin/python -m pip install \
    --no-cache-dir pytest pytest-asyncio httpx
docker compose exec api /opt/venv/bin/python -m pytest /opt/host_app/tests
```

The `-u root` is needed because `/opt/venv` is owned by root in the
runtime image; the host package itself was installed at image build
time when the Dockerfile dropped to `USER root` for that step.

**Make target** (recommended once you have more than one test invocation
to remember):

```makefile
.PHONY: test-backend
test-backend:
	docker compose exec -u root -T api /opt/venv/bin/python -m pip install \
	    --quiet --no-cache-dir pytest pytest-asyncio httpx
	docker compose exec -T api /opt/venv/bin/python -m pytest /opt/host_app/tests
```

The pip install is idempotent — it's a no-op once the deps are present
in the running container's venv. (A container restart wipes them; the
next `make test-backend` reinstalls.)

**Bake a `dev` image** (cleanest for active development, costs one
extra Docker layer and a `--target dev` flag in compose). Add a stage
to your Dockerfile after the `runtime` stage:

```dockerfile
FROM runtime AS dev
USER root
RUN /opt/venv/bin/python -m pip install --no-cache-dir \
    pytest pytest-asyncio httpx
USER app
```

…and pin the dev compose file to `target: dev`. The runtime image
stays slim; the dev image carries the test deps so `pytest` is on
PATH the moment the container boots.

## Retrofitting an existing app

Mapping an existing FastAPI/SQLAlchemy/React app onto these slots:

1. **Routers**. Each existing FastAPI router becomes
   `app.include_router(my_router)` from `init_app`. Replace any custom
   auth dependency with atrium's `current_user` (auth required) or
   `require_perm("...")` (permission required). Drop your own user /
   session / login code — it's already in atrium.

2. **Models**. Move every domain model into `<your_pkg>/models.py` and
   reparent them on `HostBase`, not your old `Base`. Atrium owns
   `users`, `roles`, `permissions`, `auth_sessions`, `email_templates`,
   `email_outbox`, `email_log`, `app_settings`, `audit_log`,
   `notifications`, `scheduled_jobs`. If your app had any of these,
   drop them — atrium's are richer.

3. **Migrations**. Start a fresh alembic chain on
   `alembic_version_app`. Don't try to port your old chain — write a
   single `0001_init.py` that creates the host tables in their final
   shape. (You can dump existing data with `mysqldump`, then load it
   after upgrade.) **Never** modify atrium's tables from your chain.

4. **Permissions**. Map your existing role/permission strings onto
   atrium's RBAC. Seed them via `seed_permissions_sync(...)` in your
   first migration. If your app had a `users.role` enum, drop it —
   atrium has no such column. Authority flows through `user_roles ->
   roles -> role_permissions`.

5. **Auth**. Delete login views, password reset, signup flows,
   sessions, JWT plumbing. Atrium provides all of it: invite-only or
   self-serve signup, two-phase 2FA (TOTP / email OTP / WebAuthn),
   password policy + HIBP, optional CAPTCHA, role-mandatory 2FA. See
   `CLAUDE.md` -> *Auth + 2FA flow*.

6. **Email**. Move templates into `email_templates` rows (composite
   key `(key, locale)`). Replace your direct `send_email(...)` calls
   with `enqueue_and_log(...)` (durable, retries) or `send_and_log(...)`
   (synchronous, for password-reset-style flows). Both write to
   `email_log` for the admin mail log.

7. **Background jobs**. Each existing cron/celery task becomes either:
   - **APScheduler tick** (`host.scheduler.add_job(...)`) for stateless,
     idempotent recurring work.
   - **`scheduled_jobs` queue handler** (`host.register_job_handler(...)`)
     for work that must survive worker restarts and have retry
     semantics.

8. **Audit**. Replace your audit log with `app.services.audit.record(...)`
   — same call signature, atrium gets impersonator-aware actor
   resolution and a UI tab for free.

9. **Frontend**. Cut the existing app shell (header, sidebar, login
   pages, profile, admin) — atrium ships all of it. Keep your domain
   pages and widgets; rebuild them as host-bundle exports that call
   the registry. The bundle's React + QueryClient stays isolated, so
   your existing component code translates almost line-for-line; only
   the entry point (`main.tsx`) and any auth/session handling
   disappears.

10. **Theme + branding**. Move colours, logo URL, brand name into
    `BrandConfig` via the admin UI (or a seed migration that PUTs
    `app_settings[brand]`). Stop writing custom Mantine theme code in
    your bundle — atrium composes the theme from `brand.preset` +
    `brand.overrides`. See [`../theme.md`](../theme.md) for the
    stability classification of the `--mantine-*` CSS custom
    properties your bundle inherits, and which subset of them
    `BrandConfig.overrides` exposes for runtime branding.

11. **i18n**. Move existing translation JSON keys into the relevant
    locale file(s) under your bundle. The atrium SPA's i18next
    instance handles the language switcher; your bundle reads from the
    same `i18n` namespace via the merged resources.

The retrofit cadence we'd recommend: stand up the new repo from this
guide, copy domain code module-by-module, run the existing test suite
against the new shape, port migrations last (so the data load happens
once on a known schema).

## Extension cheat sheet

### Backend imports from atrium

```python
# Auth
from app.auth.users import current_user, require_admin
from app.auth.rbac import require_perm
from app.auth.rbac_seed import seed_permissions_sync, seed_permissions

# DB
from app.db import get_session, get_session_factory
from app.models.auth import User
from app.models.ops import AppSetting

# Services
from app.services.audit import record as record_audit
from app.services.notifications import notify_user
from app.services.app_config import register_namespace

# Email
from app.email.sender import send_and_log, enqueue_and_log

# Jobs
from app.host_sdk.worker import HostWorkerCtx  # type for init_worker(host)

# Settings + logging
from app.settings import get_settings
from app.logging import log
```

### Job handler signature

```python
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.ops import ScheduledJob

async def handle(session: AsyncSession, job: ScheduledJob, payload: dict) -> None:
    ...
```

The runner commits after a clean return; raises mark the job FAILED
with `last_error = str(exc)`.

### Permission seeding

```python
seed_permissions_sync(
    connection,                  # op.get_bind() in a migration
    ["a.read", "a.write"],
    grants={"admin": ["a.write"]},
)
```

`super_admin` always auto-granted. Unknown role codes warn and are
skipped.

### App-config namespace

```python
from pydantic import BaseModel
from app.services.app_config import register_namespace

class FeatureFlags(BaseModel):
    new_thing: bool = False
    quota: int = 100

register_namespace("features", FeatureFlags, public=False)
```

Defaults come from the Pydantic model — never seed an `app_settings`
row in a migration. The row materialises on first PUT, and adding a
field later just gets the default on read.

### Frontend registry types

```ts
interface HomeWidget   { key: string; render: () => unknown }
interface RouteEntry   { key: string; path: string; element: unknown;
                         requireAuth?: boolean; layout?: 'shell' | 'bare' }
interface NavItem      { key: string; label: string; to: string;
                         icon?: unknown;
                         condition?: (ctx: { me: CurrentUser | null }) => boolean }
interface AdminTab     { key: string; label: string; icon?: unknown;
                         perm?: string; element: unknown }
interface ProfileItem  { key: string;
                         slot?: 'after-profile' | 'after-password' | 'after-2fa'
                              | 'after-roles' | 'after-sessions' | 'before-delete';
                         render: () => unknown;
                         condition?: (ctx: { me: CurrentUser }) => boolean }
```

Duplicate keys: last write wins, console warning. Path collisions in
`registerRoute`: same.

## Load-bearing details (don't elide these)

1. **`alembic_version_app` is the host's version table.** Set both
   `target_metadata = HostBase.metadata` and `version_table =
   "alembic_version_app"` in `alembic/env.py`. Without these the
   chains share atrium's version table and your migrations skip
   atrium's revisions (or vice versa).

2. **`%(here)s` in `alembic.ini`.** alembic is invoked from `cwd=/app`
   with `-c /opt/host_app/alembic.ini`. Without `%(here)s` the
   `script_location` resolves relative to `/app` and you'll load
   atrium's chain instead.

3. **`PYTHONPATH=/app` in compose.** The host alembic env.py imports
   `app.settings` for the DSN. Atrium's source lives at `/app` in the
   image, so it must be on PYTHONPATH no matter what CWD alembic runs
   in.

4. **Two React trees in one DOM.** atrium's React owns the wrapper
   `<div>`; the host bundle's React owns the subtree mounted via
   `createRoot` in the div's `ref` callback. Hooks never cross the
   boundary. Don't import atrium's React, don't share the
   QueryClient, don't share the MantineProvider.

5. **`window.React` and `window.__ATRIUM_REGISTRY__` exist before the
   bundle loads.** atrium's main.tsx exposes them, then dynamic-imports
   the bundle. If your bundle runs first (e.g. you `<script>` it
   directly), both will be undefined and the registrations silently
   no-op. Always go through `system.host_bundle_url`.

6. **`ATRIUM_HOST_MODULE` failures are loud.** A typo in the env var
   raises `ModuleNotFoundError` at startup. Don't suppress it; the
   operator opted in by setting it.

7. **Permissions auto-grant to `super_admin`.** `seed_permissions[_sync]`
   always grants every code to `super_admin` regardless of `grants={}`.
   Don't add it manually.

8. **Host bundle is public.** It's served from atrium's static mount
   with no auth. Don't bake secrets into it. The bundle calls
   authenticated APIs at request time; that's the auth boundary.

9. **`docker compose ... up -d --force-recreate api worker` after editing
   `.env`.** Env is captured at container start, never re-read. Changes
   made through `/admin/app-config` (branding, system flags,
   translations, auth toggles) take effect within the 2 s cache TTL
   without a restart.

10. **One image, two services.** The same `atrium-<your-app>` image
    runs both api and worker. The worker's CMD overrides to
    `python -m app.worker`. Disable the healthcheck on the worker —
    the shared image's `HEALTHCHECK` curls `/healthz`, which the
    worker has no port for.

## What lives where

| Concern                     | atrium                                     | Your host project                                  |
|-----------------------------|--------------------------------------------|----------------------------------------------------|
| Auth (password / 2FA / WebAuthn / signup) | shipped                          | nothing                                            |
| RBAC (roles, permissions)   | shipped                                    | seed your permission codes                         |
| Audit log + retention       | shipped                                    | call `record(...)` from your routes                |
| Email templates + outbox    | shipped                                    | add domain templates as rows                       |
| Scheduled jobs queue        | shipped (`scheduled_jobs` table + runner)  | register handlers                                  |
| Notifications + bell + SSE  | shipped                                    | call `notify_user(...)`                            |
| Admin app-config (brand, system, i18n, auth) | shipped (Pydantic-validated KV) | optional: register more namespaces            |
| Theme + Mantine             | shipped (presets + overrides)              | nothing — your bundle's MantineProvider is local   |
| i18n (en/nl/de/fr)          | shipped                                    | optionally add keys to your bundle's resources     |
| Maintenance mode            | shipped                                    | nothing                                            |
| Account deletion (GDPR)     | shipped                                    | nothing                                            |
| **Domain models**           | none                                       | `HostBase` + your tables                           |
| **Domain APIs**             | none                                       | your router(s)                                     |
| **Domain UI**               | shell only                                 | your bundle's widgets / pages / tabs               |
| **Domain jobs**             | none                                       | your handlers + ticks                              |

If a row in the right column is empty, you're done with that concern.
Atrium covers it. Don't reimplement.
