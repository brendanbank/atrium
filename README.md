# Atrium

A starter kit for web applications. Auth (password + TOTP + email OTP
+ WebAuthn), invite-only or opt-in self-serve signup, RBAC with
super-admin and impersonation, in-app notifications, audit log with
retention pruning, email templates with a durable retry queue,
maintenance mode, GDPR-aligned account deletion, and a scheduled-jobs
queue — all wired in and tested. Bring your own domain on top.

## Stack

- **Backend**: FastAPI + SQLAlchemy 2 (async) + Alembic, MySQL 8
- **Frontend**: React 19 + TypeScript + Vite, Mantine UI v9, TanStack
  Query, react-i18next
- **Auth**: fastapi-users with JWT cookies; RBAC (roles + permissions
  + super-admin); two-phase login with optional 2FA (TOTP / email OTP
  / WebAuthn — pick one or more)
- **Onboarding**: invite-only by default, self-serve signup +
  email-verification togglable per environment via the admin UI
- **Background jobs**: APScheduler worker with a `scheduled_jobs`
  queue (SELECT … FOR UPDATE SKIP LOCKED), three platform-owned
  built-in handlers (audit pruning, email outbox draining, account
  hard-delete), plus a host-app handler registry
- **Email**: pluggable backend (console in dev, SMTP relay in prod),
  DB-stored Jinja2 templates edited via CKEditor, durable outbox
  with exponential-backoff retries
- **Deploy**: Docker Compose. An internal nginx terminates TLS with a
  self-signed cert; you front it with whatever public proxy you like.

## Layout

```
backend/    FastAPI app, SQLAlchemy models, Alembic migrations, pytest
frontend/   React + Vite SPA, Vitest units, Playwright e2e
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

The first user you seed should be granted `super_admin` so
impersonation, privilege management, and the maintenance-mode bypass
work:

```sh
make seed-super-admin email=you@example.com password=xxxxx name='Your Name'
```

URLs:

- Frontend: <http://localhost:5173>
- API: <http://localhost:8000> (OpenAPI at `/docs`)
- MySQL: `127.0.0.1:3306`

Hot reload is on for both api (uvicorn --reload) and web (Vite HMR).

## Onboarding: invite vs self-serve

Atrium ships **invite-only** by default. To enable self-serve signup,
go to **Admin → System → Auth** (or PUT `/admin/app-config/auth`) and
flip `allow_signup`. While you're there:

- `signup_default_role_code` — the RBAC role assigned to fresh
  signups (default `user`, the zero-permission role).
- `require_email_verification` — when true (the default), accounts
  created via signup must consume the `email_verify` link before
  they can complete login. Invite-created accounts skip this gate.

The admin Users tab still works for invites either way. Invites are
multi-role (MultiSelect bound to `role_codes`).

## Configuration

Two distinct surfaces:

### Env vars (`.env`)

Set these before the stack starts. Captured at container boot and
never re-read — `docker compose up -d --force-recreate api worker`
after editing.

The minimum a fresh deploy needs (see `.env.example` for the rest):

| Var                        | What                                                    |
| -------------------------- | ------------------------------------------------------- |
| `APP_SECRET_KEY`           | long random string                                      |
| `APP_BASE_URL`             | public URL the browser hits (used in email links)        |
| `JWT_SECRET`               | long random string                                      |
| `MYSQL_*`, `DATABASE_URL`  | DB credentials + DSN                                     |
| `WEBAUTHN_RP_ID`           | host the credential is bound to (no scheme/port)         |
| `WEBAUTHN_ORIGIN`          | full origin the registration ceremony runs from          |
| `MAIL_BACKEND`             | `console` / `smtp` / `dummy` (auto-selects from env)     |
| `SMTP_*`, `MAIL_FROM`      | only when `MAIL_BACKEND=smtp`                            |
| `PUBLIC_HOSTNAME`          | baked into the prod frontend bundle                      |

### App settings (admin UI / API)

Tunable at runtime, no redeploy. Stored as JSON rows in the
`app_settings` table, validated by Pydantic models. Reach them via
**Admin → Branding / System / Translations** in the UI, or
`GET /admin/app-config` and `PUT /admin/app-config/{namespace}`.

| Namespace | Carries                                                                       |
| --------- | ----------------------------------------------------------------------------- |
| `brand`   | name, logo_url, support_email, theme preset, Mantine token overrides          |
| `system`  | maintenance_mode + message, announcement banner + level                        |
| `i18n`    | enabled_locales, per-key string overrides per locale                           |
| `auth`    | allow_signup, signup_default_role_code, require_email_verification, allow_self_delete, delete_grace_days |
| `audit`   | retention_days for the `audit_prune` job (`<= 0` = retain forever)            |

`brand`, `system`, and `i18n` (plus `auth.allow_signup` only) are
public — the frontend hits `/app-config` once at boot to seed the
theme, language switcher, and login signup-link gate. Everything
else is admin-only.

## What's in the admin UI

Out of the box you get tabs for:

- **Users** — list, invite (multi-role), edit role assignments, reset
  password, impersonate (super-admin), permanent delete (with grace
  window)
- **Roles** — create / edit / delete roles, toggle their permissions
- **Branding** — logo URL, brand name, support email, theme preset,
  ad-hoc Mantine token overrides
- **System** — maintenance mode toggle + message, announcement
  banner + level, audit retention days
- **Translations** — enabled locales, per-key string overrides per
  locale
- **Email templates** — edit subject + HTML with a CKEditor
- **Reminders** — wire scheduled emails to host-defined anchors
- **Audit** — read-only log view, filterable by entity / action

Plus, on every user's profile:

- Change own password, manage 2FA factors, view active sessions, see
  assigned roles, pick preferred language, request account deletion
  (when `auth.allow_self_delete` is on).

## Brand + theme

`Admin → Branding` exposes:

- **Brand name** — appears in the header, page titles, and email
  templates.
- **Logo URL** — defaults to the bundled `/logo.svg`. Can point
  anywhere reachable by the browser.
- **Support email** — surfaced in the account-deletion confirmation
  email and other operator-facing UX.
- **Preset** — one of `default`, `dark-glass`, `classic` (see
  `frontend/src/theme/presets/`). Each is a curated Mantine theme
  override.
- **Overrides** — a narrow dict of Mantine theme token strings the
  admin UI exposes via colour pickers + font selectors. The schema
  is intentionally narrow (`BrandConfig.overrides: dict[str, str]`)
  so we don't ship a free-form JSON editor.

The preset + overrides are merged into Mantine's theme provider in
`src/theme/ThemedApp.tsx`. Changes take effect on the next
`/app-config` refetch (typically a page navigation).

## Multi-language support

Atrium ships English, Dutch, German, and French JSON resources
(`frontend/src/i18n/locales/`). Operators control which appear in
the language switcher via `i18n.enabled_locales` (default
`["en", "nl"]`).

To override a single i18n key without forking the JSON, use
**Admin → Translations**. The override goes into
`i18n.overrides[locale][key]` and is merged on top of the bundled
resources at i18next init.

Per-user language: each User row has a `preferred_language` column.
The profile page exposes a picker; saving it writes back via
`/users/me` and i18next syncs immediately.

Email-template translations are not shipped yet; host apps that need
them either add a key-naming convention (`invite`, `invite_nl`) or
extend `email_templates` with a `language` column and switch the
template lookup. See [TODO.md](TODO.md).

## Maintenance mode

Flip `system.maintenance_mode` from **Admin → System** to put the
site into 503 mode. Bypass paths (health probes, the public
`/app-config` bundle, login + 2FA endpoints) stay reachable; users
holding the `super_admin` role pass through unrestricted so an
operator can sign in and flip the flag back. The flag is cached for
2 s — give it that long after a flip.

If you lock yourself out (no super_admin handy, can't sign in):

```sh
docker compose exec mysql mysql -u${MYSQL_USER} -p${MYSQL_PASSWORD} ${MYSQL_DATABASE} \
  -e "DELETE FROM app_settings WHERE \`key\` = 'system';"
```

The cache will expire on the next request and traffic resumes.

## Account deletion (GDPR posture)

Self-service via **Profile → Delete account** when
`auth.allow_self_delete` is on (the default). The flow:

1. User confirms with their password.
2. PII columns are anonymised in place and every active session is
   revoked. The original email gets a confirmation email with the
   scheduled hard-delete date.
3. The row stays for `auth.delete_grace_days` (default 30) so an
   operator can reinstate it.
4. The `account_hard_delete` worker handler removes the row outright
   when the grace window elapses. `audit_log.actor_user_id` is SET
   NULL'd so history survives with an anonymous actor.

Admins can delete any user (except super_admins) via **Admin →
Users**. Same pipeline.

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
at container start, never re-read. Changes made through
`/admin/app-config` (branding, system flags, translations, auth
toggles) take effect without a restart.

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
5. For runtime-tunable flags: define a Pydantic model and call
   `app.services.app_config.register_namespace("your_ns", YourModel,
   public=False)` from import-time. The admin UI surface picks it up
   automatically.
6. For background work: write a handler and register it via
   `app.jobs.runner.register_handler("your_kind", handler)` from
   `app/main.py` or `worker.py` startup.
7. For per-user notifications: call
   `app.services.notifications.notify_user(...)` from inside the
   transaction that mutated the domain row.
8. For outbound email that shouldn't block the request: call
   `app.email.sender.enqueue_and_log(...)` instead of `send_and_log`.

The frontend pattern is the same: add hooks under `src/hooks/`,
routes under `src/routes/`, mount them in `src/App.tsx`, gate with
`usePerm("…")` or `<RequireAuth role="…">`.

## License

Pick your own. Atrium ships without one — fork it, vendor it, do
whatever.
