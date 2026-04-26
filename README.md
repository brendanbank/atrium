# Atrium

A starter kit for invite-only web applications. Auth (password + TOTP +
email OTP + WebAuthn), RBAC with super-admin and impersonation, in-app
notifications, audit log, email templates, and a scheduled-jobs queue —
all wired in and tested. Bring your own domain on top.

## Stack

- **Backend**: FastAPI + SQLAlchemy 2 (async) + Alembic, MySQL 8
- **Frontend**: React 19 + TypeScript + Vite, Mantine UI v9, TanStack
  Query, react-i18next
- **Auth**: fastapi-users with JWT cookies; RBAC (roles + permissions
  + super-admin); invite-only (no public signup); two-phase login
  with mandatory 2FA (TOTP / email OTP / WebAuthn — pick one or more)
- **Background jobs**: APScheduler worker with a `scheduled_jobs`
  queue (SELECT … FOR UPDATE SKIP LOCKED) and a host-app handler
  registry
- **Email**: pluggable backend (console in dev, SMTP relay in prod),
  DB-stored Jinja2 templates edited via CKEditor
- **Deploy**: Docker Compose. An internal nginx terminates TLS with a
  self-signed cert; you front it with whatever public proxy you like.

## Layout

```
backend/    FastAPI app, SQLAlchemy models, Alembic migrations, pytest
frontend/   React + Vite SPA, Vitest units, Playwright e2e (auth, invite, logout)
infra/      mysql/, proxy/ (nginx.conf + cert gen script)
.github/    CI workflow
docker-compose.yml        prod base
docker-compose.dev.yml    dev overrides (bind mounts, host ports)
docker-compose.e2e.yml    CI e2e override (serves prod web image)
```

See [CLAUDE.md](CLAUDE.md) for a deeper walk-through of the codebase
and the conventions used.

## Local dev

```sh
cp .env.example .env
make up           # dev stack (MySQL + api + worker + web)
make migrate      # alembic upgrade head
make seed-admin email=you@example.com password=xxxxx name='Your Name'
```

The first user you seed should be granted `super_admin` so impersonation
and privilege management work:

```sh
make seed-super-admin email=you@example.com password=xxxxx name='Your Name'
```

URLs:

- Frontend: <http://localhost:5173>
- API: <http://localhost:8000> (OpenAPI at `/docs`)
- MySQL: `127.0.0.1:3306`

Hot reload is on for both api (uvicorn --reload) and web (Vite HMR).

## What's in the admin UI

Out of the box you get pages for:

- **Users** — list, invite (multi-role), edit role assignments, reset
  password, impersonate (super-admin), permanent delete
- **Roles** — create / edit / delete roles, toggle their permissions
- **Email templates** — edit subject + HTML with a CKEditor
- **Reminder rules** — wire scheduled emails to host-defined anchors
- **Audit log** — read-only view, filterable by entity / action
- **Profile** — change own password, manage 2FA factors, view active
  sessions, see assigned roles
- **Notifications** — bell + full-page list, kind-agnostic rendering
  (host apps add per-kind formatting)

## RBAC at a glance

```
permissions ─┐
              ├── role_permissions ─── roles ─── user_roles ─── users
              │
              └─ user.manage, user.impersonate, role.manage,
                 audit.read, reminder_rule.manage, …
```

Three system roles ship seeded:

| Role           | Has every permission? | Notes |
|----------------|-----------------------|-------|
| `super_admin`  | yes (incl. `user.impersonate`) | granted to the first seeded admin if `--super-admin` is passed |
| `admin`        | all except `user.impersonate`  | the everyday "operator" role |
| `user`         | none                  | host apps grant their own |

API gating uses `require_perm("…")` from `app.auth.rbac`. UI gating
uses `usePerm("…")` from `@/hooks/useAuth`. There's no single
`users.role` enum — a user can hold any combination of roles.

## Tests

```sh
make test-backend     # pytest against real MySQL (testcontainers)
make test-frontend    # vitest unit tests
make smoke            # spins up the e2e stack and runs the Playwright suite
```

CI runs backend + frontend checks, a compose build, and the smoke
test against the prod web image.

## Prod

```sh
cp .env.example .env   # then fill in real secrets, public hostname, SMTP, …
docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml run --rm api alembic upgrade head
docker compose -f docker-compose.yml run --rm api \
  python -m app.scripts.seed_admin \
    --email you@example.com --password xxxxx --full-name 'Your Name' \
    --super-admin
```

The internal proxy listens on host port `9443` with a self-signed cert
stored in the `atrium_proxy_certs` volume. Front it with a public TLS
terminator (Caddy / Traefik / Cloudflare) that does
`reverse_proxy https://<vm>:9443` with `tls_insecure_skip_verify`. The
backend honours `X-Forwarded-For` from the RFC1918 ranges, so logs
will show the real client IP.

After editing `.env` on a running stack you must
`docker compose … up -d --force-recreate api worker` — env is captured
at container start, never re-read.

## Building on top

The starter ships *only* the platform layer. To add your domain:

1. Add models in `backend/app/models/your_thing.py`, import them from
   `backend/app/models/__init__.py`.
2. Add an Alembic migration with `make migration m='add your_thing'`.
3. Add Pydantic schemas under `backend/app/schemas/`, an API router
   under `backend/app/api/`, and mount it in `backend/app/main.py`.
4. Gate routes with `Depends(require_perm("your_thing.manage"))`.
   Add the new permission codes to a follow-up migration that
   inserts into `permissions` and `role_permissions`.
5. For background work: write a handler and register it via
   `app.jobs.runner.register_handler("your_kind", handler)` from
   `app/main.py` or `worker.py` startup.
6. For per-user notifications: call
   `app.services.notifications.notify_user(...)` from inside the
   transaction that mutated the domain row.

The frontend pattern is the same: add hooks under `src/hooks/`,
routes under `src/routes/`, mount them in `src/App.tsx`, gate with
`usePerm("…")` or `<RequireAuth role="…">`.

## License

Pick your own. Atrium ships without one — fork it, vendor it, do
whatever.
