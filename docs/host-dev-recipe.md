# Host dev recipe

A working configuration for a host project layered on atrium: live-reload
on both backend and frontend, GHCR access from CI, image / static
analysis green on the first PR.

The contract surface (image catalogue, tagging, registries) lives in
[`published-images.md`](published-images.md); the from-scratch
walkthrough lives in [`new-project/`](new-project/). This page picks
up where those leave off — the integration papercuts each new host
hits in the first few days that don't surface in either of those.

The patterns below are extracted from real host integrations; the
canonical worked-example dev stack is in
[`../examples/hello-world/dev/compose.dev.yaml`](../examples/hello-world/dev/compose.dev.yaml).

## Live reload

The host dev stack runs the same atrium runtime image as prod, but
swaps **two bind mounts** to keep the edit/save loop tight:

- the host's backend package, mounted into `/host_app`, with
  `PYTHONPATH=/host_app/src:/app`
- the host's `frontend/dist`, watched by `vite build --watch` on the
  developer's host and bind-mounted into the api container at
  `/opt/atrium/static/host` (read-only)

Uvicorn runs with `--reload` (via atrium's dev compose) so editing
anything under `/host_app` triggers a backend reload. The frontend
side is dumber but cheaper: Vite rebuilds the bundle, the api
container's nginx-equivalent (FastAPI's `StaticFiles`) re-serves the
new bytes on the next page load.

Compose layout for the dev overlay:

```yaml
services:
  api:
    environment:
      ATRIUM_HOST_MODULE: <your_pkg>.bootstrap
      PYTHONPATH: /host_app/src:/app
    volumes:
      - ./backend:/host_app
      - ./frontend/dist:/opt/atrium/static/host:ro

  worker:
    environment:
      ATRIUM_HOST_MODULE: <your_pkg>.bootstrap
      PYTHONPATH: /host_app/src:/app
    volumes:
      - ./backend:/host_app
```

Frontend watcher runs on the developer's host (Vite is happier with
local fs events than container ones):

```bash
cd frontend && pnpm install && pnpm build --watch
```

### Hot-reload race

Vite's "delete + write" sequence has a brief window where
`/host/main.js` 404s and atrium's SPA shell falls back to
`index.html`. If the browser tab fetches the bundle during that
window the dynamic-import throws and the whole tab needs a refresh.
Wait for `built in <ms>` in the Vite logs before reloading the
browser tab. Don't add a polling reloader — the noise outweighs the
savings.

## GHCR image access

Atrium publishes to `ghcr.io/brendan-bank/atrium`. Three ways the
host's CI gets pull access:

1. **Public package** — recommended. No login step in CI; `docker pull`
   just works. Atrium itself is currently public.
2. **Manage Actions access (private packages)** — on the atrium
   package settings, add the host repo to "Manage Actions access",
   then in the host workflow:
   ```yaml
   permissions:
     contents: read
     packages: read
   steps:
     - uses: docker/login-action@v4
       with:
         registry: ghcr.io
         username: ${{ github.actor }}
         password: ${{ secrets.GITHUB_TOKEN }}
   ```
   `GITHUB_TOKEN` is scoped per-job, so the login is ephemeral. No
   long-lived secret in the host repo.
3. **PAT in repo secrets** — only when option 2 isn't available
   (cross-org access without inviting the host repo into the package
   ACL). Least clean; rotate manually.

For local dev the published images are pulled by Compose using your
`docker login ghcr.io` credentials (a `gh auth token`-derived PAT
works).

## Security CI checklist

Two scans, each producing SARIF that GitHub renders in the Security
tab: Trivy (image vulnerabilities) and CodeQL (source analysis).

### Workflow permissions

Both uploads call `github/codeql-action/upload-sarif`, which reads
`GET /repos/.../actions/runs/{id}` to attach run metadata. Without
`actions: read` the upload **fails silently** with "Resource not
accessible by integration" — the scan ran, the SARIF just never
lands. Always declare it on each scanning job:

```yaml
permissions:
  contents: read
  security-events: write   # SARIF upload target
  actions: read            # run-metadata fetch (silent failure without it)
```

### Code Security toggle

Private repos default to `security_and_analysis.code_security:
disabled`. CodeQL refuses to run with:

> Code Security must be enabled for this repository to use code scanning.

Click Settings → Code security & analysis → Enable, or via API:

```bash
gh api -X PATCH repos/<org>/<repo> \
  -F 'security_and_analysis[code_security][status]=enabled'
```

This is repo-level configuration, not workflow-level — a fresh host
clone fails CI on first push until someone flips the switch.

### Trivy

Image scan, post-build:

```yaml
- name: Build host image
  run: docker build -t host-app:ci .

- name: Trivy scan
  uses: aquasecurity/trivy-action@<sha>
  with:
    image-ref: host-app:ci
    format: sarif
    output: trivy-results.sarif
    severity: CRITICAL,HIGH

- name: Upload SARIF
  uses: github/codeql-action/upload-sarif@<sha>
  with:
    sarif_file: trivy-results.sarif
    category: trivy
```

### CodeQL

Two-language matrix (Python + TypeScript) is typical. The host's
`.github/codeql/codeql-config.yml` should exclude generated /
vendored paths so the diff stays signal-only:

```yaml
paths-ignore:
  - frontend/dist
  - frontend/node_modules
  - backend/.venv
  - "**/_generated_*.py"
```

### Dependabot

One config file at `.github/dependabot.yml`, grouped so a Tuesday
morning isn't six identical Mantine bumps:

```yaml
version: 2
updates:
  - package-ecosystem: pip
    directory: /backend
    schedule: { interval: weekly }
    groups:
      backend: { patterns: ["*"] }

  - package-ecosystem: npm
    directory: /frontend
    schedule: { interval: weekly }
    groups:
      mantine: { patterns: ["@mantine/*"] }
      tanstack: { patterns: ["@tanstack/*"] }
      lint: { patterns: ["eslint*", "@typescript-eslint/*", "prettier"] }
      typescript: { patterns: ["typescript", "@types/*", "tsx"] }

  - package-ecosystem: github-actions
    directory: /
    schedule: { interval: weekly }
    groups:
      actions: { patterns: ["*"] }
```

## Backend test stack

Use `testcontainers-mysql` against MySQL 8.0 — the same engine
atrium uses, so timezone / collation / `DATETIME(0)` rounding
behaviour matches prod.

Two alembic chains run against the same database:

- atrium's chain (`alembic upgrade head` from `/app`) — owns the
  `alembic_version` table.
- the host chain (`alembic -c /host_app/alembic.ini upgrade head`)
  — owns `alembic_version_app` (from `version_table` in the host's
  `env.py`). See [`new-project/README.md`](new-project/README.md)
  step 5 for the exact `env.py`.

A pytest conftest pattern that drops + recreates the DB per test
session and runs both chains keeps tests independent of each other
and matches what atrium's own test suite does. Don't truncate inside
test bodies — atrium's role / permission seed lives in the schema
migration, so a TRUNCATE between tests wipes the row that
`require_perm` looks up.

## Frontend test stack

- **Vitest** for unit tests (host hooks, registry calls,
  string-formatter helpers). Runs in seconds; no server required.
- **Playwright** for end-to-end (auth flow, host route, bell + SSE).
  Requires the full compose stack — see the hello-world
  `e2e` workflow for the canonical shape.

Login helpers want `E2E_ADMIN_EMAIL`, `E2E_ADMIN_PASSWORD`, and a
fixed `E2E_ADMIN_TOTP_SECRET`. In CI those come from workflow env;
in local dev, store the seeded admin creds in 1Password and source
them via `op run --` for the test command.

Atrium ships a typed [`AtriumEvent`](../frontend/src/host/events.ts)
contract for SSE payloads; host bundles using
`subscribeEvent('<kind>', handler)` should mirror the same shape in
their tests so payload assertions stay aligned with the wire
format.

## Reference layout

- [`../examples/hello-world/`](../examples/hello-world/) — full
  worked example. Backend host package, frontend bundle, alembic
  chain, compose, dev overlay.
- [`../examples/hello-world/dev/compose.dev.yaml`](../examples/hello-world/dev/compose.dev.yaml)
  — the canonical dev overlay this page summarises.
- [`new-project/`](new-project/) — from-scratch bootstrap walkthrough.
- [`published-images.md`](published-images.md) — the registry +
  extension contract.
