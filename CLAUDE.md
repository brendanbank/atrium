# CLAUDE.md

Orientation for an AI assistant (or new human contributor) dropping
into the Atrium starter. Read this before grep-ing — it covers the
architecture, the non-obvious conventions, and the places where
things have burned us before.

## One-sentence summary

Atrium is a starter kit for invite-only web applications: FastAPI +
SQLAlchemy + MySQL on the back, React + Mantine + TanStack Query on
the front, with auth (password + TOTP + email OTP + WebAuthn), RBAC
(roles + permissions + super-admin + impersonation), in-app
notifications, audit log, email templates, and a scheduled-jobs
queue all wired in and tested.

It's not opinionated about your domain — it ships *only* the
platform layer. Bring your own bookings, posts, invoices, whatever.

## Stack at a glance

| Layer        | What                                                    |
| ------------ | ------------------------------------------------------- |
| API          | FastAPI, SQLAlchemy 2 async, Alembic, fastapi-users     |
| DB           | MySQL 8 (async via `aiomysql`)                          |
| Worker       | APScheduler driving `app.jobs.runner.run_one`           |
| Frontend     | React 19 + TypeScript + Vite, Mantine v9, TanStack Query|
| Tests        | pytest + testcontainers-mysql, Vitest, Playwright       |
| Deployment   | Docker Compose, nginx with self-signed cert             |

## Repository layout

```
backend/
  app/
    api/
      admin_roles.py, admin_users.py    user + role CRUD
      audit.py                          audit-log read endpoint
      email_otp.py, totp.py, webauthn.py login + 2FA
      email_templates.py                template CRUD
      health.py                         /healthz, /readyz, /health
      impersonate.py                    super-admin tooling
      invites.py                        invite create/list/revoke/accept
      me_context.py                     /users/me/context (RBAC view)
      notifications.py                  bell list + SSE stream
      reminder_rules.py                 reminder-rule CRUD
      sessions.py                       active sessions, logout-all
    auth/         fastapi-users wiring, scope skeleton, RBAC helpers
    db.py         engine, session factory, Base
    email/        Jinja2 templates + pluggable backend (console/smtp/dummy)
    jobs/         scheduled_jobs queue + worker + handler registry
    models/       SQLAlchemy mapped classes
    schemas/      Pydantic request/response models
    scripts/      seed_admin and similar one-shots
    services/
      audit.py, notifications.py    audit log + in-app notification helper
      event_hub.py                  in-process pub/sub for SSE
      rate_limit.py                 auth-endpoint rate limiter
      totp.py                       pyotp wrapper
    main.py, settings.py, worker.py
  alembic/        Migration chain (head: 0001_atrium_init)
  tests/          api/, integration/, unit/

frontend/
  src/
    components/   Shared UI (NotificationsBell, RequireAuth, admin/…)
    hooks/        useAuth, useUsersAdmin, useNotificationStream, …
    routes/       Page-level components (one per /route)
    lib/
      api.ts                         Axios instance
      auth.ts, money.ts, types.ts    shared helpers + types
      queryClient.ts, theme.ts
    i18n/locales/ en.json (nl.json placeholder)
  tests-e2e/      Playwright smoke + auth specs

infra/
  mysql/my.cnf
  proxy/nginx.conf, gen-cert.sh   internal TLS terminator (prod)

docker-compose.yml        prod
docker-compose.dev.yml    dev overrides: bind mounts, --reload, host ports
docker-compose.e2e.yml    CI e2e: uses the prod web image on :9443
Makefile                  up/down/migrate/seed-admin/test/smoke
```

## RBAC contract (the most load-bearing decision)

Atrium has **no** `users.role` enum. Authority flows entirely through
RBAC:

```
permissions (code PK)         user.manage, audit.read, …
roles (id PK, code UNIQUE)    admin, super_admin, user, …
role_permissions              roles ↔ permissions (M:N)
user_roles                    users ↔ roles (M:N)
```

A user holds zero or more roles via `user_roles`. Their effective
permission set is the union over those roles' `role_permissions`.

**Three system roles** seeded by `0001_atrium_init`:

- `super_admin` — every permission, including `user.impersonate`. The
  privilege-escalation guard in `admin_users.update` prevents anyone
  *not* already super_admin from granting it.
- `admin` — every permission *except* `user.impersonate`.
- `user` — no permissions. Host apps grant their own.

**Eight default permissions** (atrium-relevant; host apps add more):

- `user.manage`, `user.impersonate`, `user.totp.reset`
- `role.manage`
- `audit.read`
- `reminder_rule.manage`
- `email_template.manage`
- `app_setting.manage`

**API gating**: every router uses `require_perm("…")` from
`app.auth.rbac`. `require_admin` exists in `app.auth.users` as a
shortcut for the "any user with the `admin` role" case, but prefer
`require_perm` for finer-grained control.

**Wire format**: roles are referenced by **code** (stable string)
when atrium creates / accepts / impersonates, and by **id** when the
admin UI edits an existing user's role assignments. Both work; the
mismatch is intentional (codes are environment-portable, ids are
what the existing `UserAdminUpdate.role_ids` patch already shipped).
Pick one for a future cleanup pass if it bothers you.

**Invites are multi-role**: `UserInvite.role_codes: list[str]` (JSON
column). The accept flow loops and assigns each. The InviteModal in
the admin UI uses a MultiSelect bound to `role_codes`.

## Auth + 2FA flow

Three second-factor methods, any combination, per user:

- **TOTP** (`pyotp`, SHA-1 / 6-digit / 30s — universal authenticator
  app compatibility)
- **Email OTP** (6-digit, sha256-hashed, 10-min TTL)
- **WebAuthn / FIDO2** (`py_webauthn`, multiple credentials per user,
  touch-only — `user_verification=DISCOURAGED` +
  `resident_key=DISCOURAGED`, matches AWS's flow)

Login is **two-phase**. Password creates an `auth_sessions` row with
`totp_passed=False`; every domain endpoint's `current_user` dep
returns 403 `{code: "totp_required"}` until the appropriate
`/auth/{totp,email-otp,webauthn}/{confirm,verify,authenticate/finish}`
call flips the flag. The frontend turns the 403 into a redirect to
`/2fa`.

`/2fa` auto-triggers WebAuthn on mount when the user has a registered
credential; TOTP / email OTP are fallbacks.

Auth cookies: `atrium_auth` (the JWT carrying `sid`) and
`atrium_impersonator` (the actor cookie when a super_admin is
viewing-as someone). The `sid` lookup against `auth_sessions` makes
logout, logout-all, and admin revocation real (not JWT-stateless).

Tests that need the real 2FA gate carry
`pytestmark = pytest.mark.real_2fa`; everything else auto-passes via
the `_auto_pass_2fa` conftest fixture so each test doesn't have to
drive the full challenge.

## Scheduled jobs (handler registry)

Atrium ships the queue plumbing but **no built-in job handlers**.
Host apps register handlers at startup:

```python
from app.jobs.runner import register_handler

async def send_welcome_email(session, job, payload):
    ...

register_handler("welcome_email", send_welcome_email)
```

`scheduled_jobs` rows carry an opaque `entity_type` + `entity_id` so
the host can attribute a job to a domain row without a hard FK. The
runner claims a row via `next_due_job` (FOR UPDATE SKIP LOCKED),
looks up the handler, runs it, marks `done`/`failed`. Jobs without a
registered handler get cancelled with an explanatory `last_error` —
loud failure, not silent stuck rows.

`reminder_rules` is the table behind the admin "schedule reminders"
UI. Fields: `name`, `template_key` (FK to `email_templates`),
`anchor` (free-form string), `kind` (free-form string), `days_offset`
(signed int), `active`. Atrium ships **no** anchors or kinds — the
host app decides what they mean and writes the logic that turns a
rule into a `ScheduledJob` row.

## Notifications + SSE

`Notification` rows are written via
`app.services.notifications.notify_user(session, user_id=…, kind=…,
payload={…})`. The helper does two things:

1. `session.add(Notification(…))` — caller controls the transaction,
   so the row only lands if the surrounding work commits.
2. `event_hub.publish(user_id, {"kind": "refresh"})` — fires an
   in-process pub/sub event the SSE stream picks up so the bell
   refetches instantly.

The SSE endpoint (`/notifications/stream`) sends a keepalive every
25 s and disables nginx buffering. The bell UI is **kind-agnostic** —
each row renders its `kind` code + a "View" button that opens the
raw JSON payload. Host apps add per-kind formatting.

## Email

`app.email.backend.get_mail_backend` auto-selects from `MAIL_BACKEND`
env (`console` / `smtp` / `dummy`). Unset → falls back to `smtp`
when `ENVIRONMENT=prod`, else `console`.

Templates live in the `email_templates` table (key, subject,
body_html, description) and are rendered with Jinja2. Plain-text is
derived from the HTML by tag-stripping. Autoescape is ON — a guest
name like `<script>…</script>` renders as harmless text.

Four default templates seeded by `0001_atrium_init`:

- `invite` — sent to a fresh invitee with the accept link
- `password_reset` — self-service reset
- `admin_password_reset_notice` — heads-up to the target when an
  admin triggers a reset on someone else's account (so a silent
  takeover attack is visible)
- `email_otp_code` — six-digit code delivered when a user picks
  email-OTP at the `/2fa` challenge

Invite links are rendered from `settings.app_base_url` — set this to
the public URL on prod (`https://app.example.com`), not `localhost`.

`send_and_log` accepts optional `entity_type` + `entity_id`
parameters that get written to the corresponding `email_log` columns.
Use them when you want to attribute an email to a domain row.

## Audit log

`app.services.audit.record(...)` is the only place that writes
`audit_log`. Diff values are coerced to JSON-safe types by
`_json_safe` (dates, Decimals, Enums → strings).

When a super_admin is impersonating someone, the audit middleware
populates a ContextVar from the `atrium_impersonator` cookie and
`record(...)` reads it to set `audit_log.impersonator_user_id`.
That's how the audit trail distinguishes "target did X" from
"super_admin did X while impersonating target".

## Backend conventions

- Async everywhere. Never mix sync `Session` with async routes.
- When an async handler needs to read a server-defaulted column
  (`created_at`, `updated_at`) on an object it just inserted, call
  `session.refresh(obj, attribute_names=["…"])`.
- Add new Alembic migrations under
  `backend/alembic/versions/YYYY_MM_DD_NNNN-*.py`. Keep the chain
  linear (never branch) and include both upgrade and downgrade.
  Current head: `0001_atrium_init`.
- `B008` is silenced for `fastapi.Depends`, `fastapi.Query`, etc. via
  `extend-immutable-calls`. Don't refactor `Depends(...)` calls to
  dodge the lint.
- `RUF001`/`RUF003` flag ambiguous unicode (em-dash, typographic
  quotes) — use ASCII hyphens in source.

## Frontend conventions

- Mantine v9 only. Dark mode uses Mantine's color scheme attribute.
- One Axios instance in `src/lib/api.ts`. It sends cookies
  (`withCredentials: true`) and bounces to `/login` on a 401, except
  on the `/users/me` probe.
- TanStack Query keys are string arrays exported at the top of the
  hook modules (`USERS_KEY`, `INVITES_KEY`, etc.). Invalidating or
  refetching uses these — don't inline the key literals.
- `RequireAuth` guards routes; it treats `isLoading || (data == null
  && isFetching)` as "still loading" so the cached `null` from the
  pre-login `/users/me` probe can't bounce a freshly logged-in user.
- The `/users/me/context` endpoint returns `{ id, email, full_name,
  is_active, roles: string[], permissions: string[],
  impersonating_from }`. UI gates use `roles.includes("admin")` or
  `usePerm("…")` — never compare against a single role string.
- CKEditor 5 is loaded from the CDN (see `index.html`); the
  `VITE_CKEDITOR_LICENSE_KEY` is injected via Vite HTML
  `%VITE_*%` substitution. Set it to `GPL` to use the free tier.

## Testing

- **Backend**: `make test-backend` runs pytest against MySQL 8
  (testcontainers in dev, a GitHub Actions service on CI). The
  session fixture TRUNCATEs after every test but preserves
  `app_settings`, `email_templates`, and `permissions` (those are
  invariant across tests). `roles` + `role_permissions` ARE truncated
  and re-seeded per test (`_reseed_rbac`) because admin tests
  legitimately mutate them.
- **Frontend**: `pnpm test` = vitest unit tests. `pnpm playwright
  test` = Playwright specs.
- **Smoke**: `make smoke` brings up the e2e stack (prod web image via
  `docker-compose.e2e.yml`), seeds an admin, and runs the Playwright
  suite. Run before pushing anything that touches auth, the app
  shell, or the login flow.
- When running Vitest or Playwright from the host, use the dev web
  container (`docker compose exec web node_modules/.bin/vitest run …`)
  because pnpm's virtual store doesn't expose the binary at
  `node_modules/.bin/` on the host.

### CI

- `.github/workflows/ci.yml` runs on **pull requests only** (no push
  events on main). Jobs: `backend`, `frontend`, `e2e`,
  `compose-build`.
- The e2e job uses the prod nginx image — this is deliberate. The
  dev vite + pnpm + bind-mount + named-volume combination was fragile
  on ephemeral runners (postcss would go missing from the pnpm
  virtual store). Serving the already-built bundle is closer to
  production and has no moving parts at request time.

## Deployment

### Topology

```
(internet)
    │  TLS
    ▼
edge proxy (your firewall)             ← terminates public TLS
    │  TLS (self-signed origin)
    ▼
proxy (nginx:alpine, :9443)            ← this repo; trusts XFF from edge
    │  HTTP (docker network)
    ├── /api/*  →  api  (FastAPI on :8000, rewrite strips /api)
    └── /*      →  web  (nginx:alpine serving built dist)
            │
            └── mysql + worker inside the same compose
```

`infra/proxy/gen-cert.sh` generates a self-signed cert at first boot
into the `atrium_proxy_certs` volume — stable across restarts, wipe
the volume to rotate. `set_real_ip_from 10/8,172.16/12,192.168/16`
means the proxy trusts the edge's `X-Forwarded-For`, so the backend
sees the real client IP.

### Config

- `.env` is the only config surface. `docker-compose.yml` reads it
  via `env_file`. Compose v2 expands `${VAR}` inside `.env`, so the
  DSN can reference `${MYSQL_USER}` etc.
- The frontend bundle is built with `VITE_API_BASE_URL=/api`
  (relative). One image works regardless of which hostname the
  browser arrived on — handy when you hit the VM directly for
  testing on `:9443`.

### First deploy on a new box

See `README.md` → **Prod** for the exact sequence. After editing
`.env` on a running stack you must `docker compose … up -d
--force-recreate api worker` — env is captured at container start,
never re-read.

## Things to remember

Failure modes that still apply to atrium:

1. **MySQL DATETIME(0) rounds half-up.** Setting `run_at = now()`
   from Python can land you a few hundred ms in the future and break
   `run_at <= now()` on the next query. Subtract a second when
   seeding.
2. **APScheduler `next_run_time=None` pauses jobs permanently.**
   Don't set it — let the scheduler compute it.
3. **Async SQLAlchemy lazy-load fails with `MissingGreenlet`.**
   `refresh(obj, attribute_names=["created_at"])` is the fix.
4. **fastapi-users login returns 400 on bad credentials**, not 401.
   The frontend checks both.
5. **TanStack Query `invalidateQueries` keeps stale data.** On logout
   use `queryClient.clear()`. Otherwise the next login mounts with
   the previous session's `/auth/totp/state.session_passed=true`
   still in cache and the `/2fa` redirect effect bounces past the
   gate before the refetch lands.
6. **nginx `add_header` inheritance is all-or-nothing.** A single
   `add_header` inside a `location` drops every header defined at
   `server` scope for that response. If you add a per-location
   header, re-list HSTS / nosniff / referrer-policy /
   permissions-policy explicitly.
7. **Compose `.env` interpolation is Compose-only.** Anything that
   reads `.env` outside Compose (shells, pytest outside containers)
   sees the literal `${VAR}`.
8. **Postfix `mynetworks` must include the docker bridge** for
   `MAIL_BACKEND=smtp` to relay — otherwise Postfix rejects with
   `Client host rejected`.

## Session expectations for an AI assistant

- Prefer editing existing files over creating new ones.
- Keep user-facing text short; details go in this file or the README,
  not in chat.
- Don't introduce frameworks, feature flags, or abstractions beyond
  what the current task needs.
- Run `pnpm typecheck` / `pytest` before declaring anything done if
  the change wasn't trivial. For the frontend you'll usually want to
  run these inside the dev web container.
- For UI tweaks, watch HMR logs — Vite will tell you if a file failed
  to transform.
