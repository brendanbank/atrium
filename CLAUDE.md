# CLAUDE.md

Orientation for an AI assistant (or new human contributor) dropping
into the Atrium starter. Read this before grep-ing — it covers the
architecture, the non-obvious conventions, and the places where
things have burned us before.

## One-sentence summary

Atrium is a starter kit for web applications: FastAPI + SQLAlchemy +
MySQL on the back, React + Mantine + TanStack Query on the front,
with auth (password + TOTP + email OTP + WebAuthn + self-serve
signup), invite-only OR opt-in self-serve registration, configurable
password policy (length / character classes / HIBP breach lookup),
role-mandatory 2FA enrollment, optional CAPTCHA (Turnstile or
hCaptcha) on the unauthenticated auth endpoints, RBAC (roles +
permissions + super-admin + impersonation), admin app-config
(branding, system, translations, auth), audit log + retention
pruning, in-app notifications, email templates with a durable outbox
and per-locale variants (en / nl / de / fr seeded), maintenance
mode, GDPR-aligned account deletion, and a scheduled-jobs queue all
wired in and tested.

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
      account_deletion.py               self + admin /delete endpoints
      admin_roles.py, admin_users.py    user + role CRUD
      app_config.py                     /app-config + /admin/app-config
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
      signup.py                         /auth/register + /auth/verify-email
    auth/         fastapi-users wiring, scope skeleton, RBAC helpers
    db.py         engine, session factory, Base
    email/        Jinja2 renderer + pluggable backend (console/smtp/dummy)
    jobs/
      runner.py             handler registry + claim loop
      schedule.py           next_due_job
      builtin_handlers.py   audit_prune, email_send, account_hard_delete
    models/       SQLAlchemy mapped classes (incl. email_outbox,
                  email_verification, soft-delete cols on User)
    schemas/      Pydantic request/response models
    scripts/      seed_admin and similar one-shots
    services/
      account_deletion.py  soft-delete + anonymise + grace window
      app_config.py        Pydantic-namespace KV reader/writer
      audit.py             audit-log writer
      audit_retention.py   DELETE FROM audit_log retention helper
      captcha.py           Turnstile/hCaptcha verifier + login middleware
      event_hub.py         in-process pub/sub for SSE
      maintenance.py       MaintenanceMiddleware (503 + super_admin bypass)
      notifications.py     in-app notification helper
      password_policy.py   policy validator + HIBP k-anon lookup
      rate_limit.py        AuthRateLimitMiddleware
      signup.py            register_user + consume_verification
      totp.py              pyotp wrapper
    main.py, settings.py, worker.py
  alembic/        Migration chain (head: 0005_email_template_per_locale)
  tests/          api/, integration/, unit/

frontend/
  src/
    components/
      AnnouncementBanner.tsx      banner driven by system.announcement
      MaintenancePage.tsx         shown to non-super-admins on 503
      NotificationsBell.tsx, RequireAuth, ImpersonationBanner, …
      admin/
        BrandingAdmin.tsx         logo + brand name + preset + tokens
        SystemAdmin.tsx           maintenance + announcement + retention
        TranslationsAdmin.tsx     enabled locales + per-key overrides
        UsersAdmin, RolesAdmin, EmailTemplatesAdmin, RemindersAdmin,
        AuditAdmin
    hooks/
      useAppConfig.ts             public bundle + admin namespaces
      useAccountDeletion.ts
      useAuth, useUsersAdmin, useNotificationStream, …
    routes/
      RegisterPage.tsx            self-serve signup
      VerifyEmailPage.tsx         consumes the verification token
      AcceptInvitePage, AdminPage, HomePage, LoginPage,
      NotificationsPage, ProfilePage, TwoFactorPage,
      ForgotPasswordPage, ResetPasswordPage
    theme/
      index.ts                    base Mantine theme
      ThemedApp.tsx               applies brand + preset + overrides
      presets/                    "default", "dark-glass", "classic"
    lib/
      api.ts                      Axios instance (cookies + 401 → /login)
      auth.ts, money.ts, types.ts, queryClient.ts, notifications.ts
    i18n/locales/ en.json, nl.json, de.json, fr.json
  tests-e2e/
    smoke, email-otp, webauthn, invite-flow, logout, branding,
    i18n, maintenance, account-deletion, profile-language

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
- `user` — no permissions. Host apps grant their own. This is also
  the default role assigned to fresh self-serve signups (via
  `auth.signup_default_role_code`).

**Eight default permissions** (atrium-relevant; host apps add more):

- `user.manage`, `user.impersonate`, `user.totp.reset`
- `role.manage`
- `audit.read`
- `reminder_rule.manage`
- `email_template.manage`
- `app_setting.manage` — gates the entire `/admin/app-config` surface
  (Branding, System, Translations tabs).

**API gating**: every router uses `require_perm("…")` from
`app.auth.rbac`. `require_admin` exists in `app.auth.users` as a
shortcut for the "any user with the `admin` role" case, but prefer
`require_perm` for finer-grained control.

**Wire format**: roles are referenced by **code** (stable string)
when atrium creates / accepts / impersonates, and by **id** when the
admin UI edits an existing user's role assignments. Both work; the
mismatch is intentional (codes are environment-portable, ids are
what `UserAdminUpdate.role_ids` ships).

**Invites are multi-role**: `UserInvite.role_codes: list[str]` (JSON
column). The accept flow loops and assigns each. The InviteModal in
the admin UI uses a MultiSelect bound to `role_codes`.

## App configuration (the most load-bearing decision after RBAC)

Atrium splits configuration into two surfaces:

- **Env vars** (`.env`, read by `app.settings.get_settings`) — secrets,
  infrastructure, build-time identity, anything per-environment that
  has to be set before the app starts. JWT secret, DSN, WebAuthn RP
  ID, mail backend, public hostname.
- **`app_settings` table** — admin-tunable product behavior and
  branding. Mutable at runtime via `/admin/app-config`. Anything the
  operator might want to flip without a redeploy.

The `app_settings` table is a key-JSON KV store. Each *namespace* is
one row, validated on read and write through a Pydantic model
registered in `app.services.app_config.NAMESPACES`:

| Key       | Model         | Public? | What it carries                                          |
| --------- | ------------- | ------- | -------------------------------------------------------- |
| `brand`   | `BrandConfig` | yes     | name, logo_url, support_email, preset, theme overrides    |
| `i18n`    | `I18nConfig`  | yes     | enabled_locales, per-key string overrides                 |
| `system`  | `SystemConfig`| yes     | maintenance_mode + message, announcement + level          |
| `auth`    | `AuthConfig`  | no      | allow_signup, signup_default_role_code, require_email_verification, allow_self_delete, delete_grace_days, password_min_length, password_require_mixed_case, password_require_digit, password_require_symbol, password_check_breach, require_2fa_for_roles, captcha_provider, captcha_site_key |

`audit.retention_days` lives in the same table under the `audit` key,
read directly by the `audit_prune` job (no Pydantic namespace yet —
add one if it grows fields).

**Public vs admin** is enforced in `services/app_config.py`, not at
the route layer. `GET /app-config` (no auth) bundles every `public=True`
namespace plus a hand-picked carve-out from `AuthConfig`:
`allow_signup` (so `/login` can render the "Sign up" link),
`captcha_provider`, and `captcha_site_key` (the site key is public
by design — the widget renders it into the page). Everything else
on `AuthConfig` (password policy, role-mandatory 2FA list,
self-delete + grace window, signup defaults, email-verification
toggle) stays admin-only. Anything policy- or security-adjacent
(password rules, retention, CAPTCHA secret) belongs in admin-only
namespaces or env vars.

**Defaults come from the Pydantic model**, not from a migration —
there's no row to seed. The first PUT materialises one.
`model_validate` on read re-applies defaults for any field added
since the row was last written, so adding a new `BrandConfig` field
doesn't require a backfill migration.

**Registering a new namespace**: from any module that imports at
startup, call

```python
from app.services.app_config import register_namespace
from pydantic import BaseModel

class FeatureFlags(BaseModel):
    new_thing: bool = False

register_namespace("features", FeatureFlags, public=False)
```

The `/admin/app-config` admin endpoint picks it up automatically;
`get_public_config` only includes it if `public=True`.

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
returns 403 with one of two `code` values until the appropriate
`/auth/{totp,email-otp,webauthn}/{confirm,verify,authenticate/finish}`
call flips the flag:

- `totp_required` — the user has at least one confirmed 2FA factor;
  the SPA shows the challenge screen at `/2fa`.
- `2fa_enrollment_required` — the user holds a role listed in
  `auth.require_2fa_for_roles` but has zero confirmed factors. The
  SPA still routes to `/2fa` (which surfaces the setup picker for
  unenrolled users) but the distinct code lets the UI render a
  clearer "your account requires 2FA" hint. The check fires on both
  partial and full sessions, so a super_admin admin reset that
  wipes a user's factors mid-session re-bounces them to enrollment
  on the next request.

Both codes are routed by the frontend's axios interceptor in
`src/lib/api.ts` to `/2fa`. `/2fa` auto-triggers WebAuthn on mount
when the user has a registered credential; TOTP / email OTP are
fallbacks.

**Password policy** lives in `app.services.password_policy`
(`validate_password_against_policy`). The validator reads
`AuthConfig` and runs cheap structural checks first (min length,
mixed case, digit, symbol), then — if `password_check_breach` is on
— an HIBP k-anonymity range lookup as a final gate. The HIBP call
is fail-open with a 5-minute per-prefix in-memory cache: an upstream
incident at HIBP must not lock every user out of registration. The
validator is wired into both the self-serve `/auth/register` flow
and the invite-accept flow. All four toggles ship **on** by default
so a fresh atrium starts with a safe baseline; relax them per
deployment. The backend test conftest patches the HIBP fetcher to
return None (fail-open) so test suites don't depend on the network;
tests that exercise the breach branch override the patch in their
body.

**CAPTCHA** is opt-in (`auth.captcha_provider`: `none` /
`turnstile` / `hcaptcha`). When on, `CaptchaLoginMiddleware` reads
the request body once, extracts `captcha_token`, and verifies it
against the provider's `siteverify` endpoint before fastapi-users
sees the login. The site key is public (rendered into the widget on
`/login` and `/forgot-password`); the secret lives in the
`CAPTCHA_SECRET` env var so it never round-trips through the
`/app-config` bundle. Verification is fail-open on network /
upstream failure for the same reason HIBP is.

**Email-verification gate**: when `auth.require_email_verification`
is on (the default), accounts created via self-serve signup must
consume the verification link before they can complete login.
`users.email_verified_at` is the gate; `is_verified` (the
fastapi-users field) is kept in sync but the login refusal reads
`email_verified_at` so existing invite-created accounts (which never
went through self-serve verification) still pass.

Auth cookies: `atrium_auth` (the JWT carrying `sid`) and
`atrium_impersonator` (the actor cookie when a super_admin is
viewing-as someone). The `sid` lookup against `auth_sessions` makes
logout, logout-all, and admin revocation real (not JWT-stateless).

Tests that need the real 2FA gate carry
`pytestmark = pytest.mark.real_2fa`; everything else auto-passes via
the `_auto_pass_2fa` conftest fixture so each test doesn't have to
drive the full challenge.

## Maintenance mode

`SystemConfig.maintenance_mode` is the global kill-switch. When on,
`MaintenanceMiddleware` short-circuits every request with HTTP 503
and a JSON body `{"detail":"maintenance","message":...,"code":"maintenance_mode"}`,
except:

- **Bypass paths** (always reachable): `/healthz`, `/readyz`,
  `/health`, `/app-config`, `/auth/jwt/login`, `/auth/jwt/logout`,
  `/users/me`, `/users/me/context`, plus prefixes
  `/auth/totp/`, `/auth/email-otp/`, `/auth/webauthn/`. The login +
  2FA paths stay live so a super_admin can sign in to flip the flag
  off; `/app-config` stays live so the frontend can fetch the
  maintenance message and render the maintenance page itself.
- **Super_admin bypass**: any cookie that maps to a live, full-2FA
  `auth_sessions` row whose user holds the `super_admin` role
  passes through.

The flag is read on every request, so it's cached in-process for
**2 seconds** (`_TTL_SECONDS`). Long enough to keep the hot path off
the DB, short enough that flipping the flag in the admin UI feels
instant.

**Recovery path** if you accidentally lock yourself out: a
super_admin login completes in two POSTs (`/auth/jwt/login` +
`/auth/totp/verify`), both on the bypass list. If you don't have
super_admin handy, drop the row directly:
`DELETE FROM app_settings WHERE \`key\` = 'system';` and wait 2 s for
the cache to expire.

The frontend hits `/app-config` on boot and shows
`MaintenancePage` to non-super-admins when `system.maintenance_mode`
is true. The `AnnouncementBanner` reads `system.announcement` (plain
text, max 2000 chars) and renders one of three Mantine alert levels
based on `announcement_level`.

## Email pipeline

Two send paths:

- **`send_and_log`** (`app/email/sender.py`) — synchronous render +
  send + log. Use it when the user is waiting for the email
  delivery to complete (signup verification email, password reset).
  Render failures raise `RuntimeError` after recording a
  `[render failed]` `EmailLog` row; SMTP failures raise after
  recording a `failed` row. Both write `email_log` so the admin mail
  log makes the break visible.

- **`enqueue_and_log`** — durable queue. Inserts one
  `email_outbox` row per recipient (`status=pending`,
  `next_attempt_at=now`) plus a `queued` `email_log` row. The
  template existence is validated up-front so a typo fails the
  caller's request synchronously instead of leaving a stuck row.
  The `email_send` built-in handler (`app/jobs/builtin_handlers.py`)
  drains pending rows with **exponential backoff**: 60 s, 5 min,
  30 min, 2 h, 12 h, then dead-letter. `MAX_ATTEMPTS = 6`. A
  terminal `sent` or `dead` writes a final `email_log` row that
  mirrors what really happened.

Use `enqueue_and_log` for fan-out (notification batches), anything
that doesn't need to block the request, or anything where the SMTP
relay's flakiness shouldn't surface as a 500. Use `send_and_log`
when the user-visible flow depends on knowing the email went out.

Templates live in the `email_templates` table, **composite-keyed on
`(key, locale)`** (since `0005_email_template_per_locale`), and are
rendered with Jinja2. Plain-text is derived from the HTML by
tag-stripping. Autoescape is ON — a guest name like
`<script>…</script>` renders as harmless text.

`render_template(session, key, context, locale="en")` (and the two
sender helpers that wrap it) resolves the variant in this order:

1. The recipient's `preferred_language` (or whatever the caller
   passes as `locale`) — `(key, locale)` row.
2. Fallback to `(key, 'en')` if the requested locale has no row.
3. `LookupError` if neither exists. The caller writes a `[render
   failed]` `email_log` row + structlog ERROR; nothing silent.

`enqueue_and_log` persists the resolved `locale` on the
`email_outbox` row so the `email_send` worker re-renders against the
same variant on retry — a recipient who registered in Dutch still
gets the Dutch body when the SMTP relay comes back online, even if
they've changed `preferred_language` between enqueue and drain.

Default templates seeded by `0001_atrium_init` /
`0004_email_verifications` (English) and `0005_email_template_per_locale`
(nl / de / fr translations of every template below):

- `invite` — sent to a fresh invitee with the accept link
- `password_reset` — self-service reset
- `admin_password_reset_notice` — heads-up to the target when an
  admin triggers a reset on someone else's account (so a silent
  takeover attack is visible)
- `email_otp_code` — six-digit code delivered when a user picks
  email-OTP at the `/2fa` challenge
- `email_verify` — self-serve signup verification link
- `account_delete_confirm` — confirmation + scheduled hard-delete
  date, sent at the moment of soft-delete
- `account_delete_admin_notice` — heads-up to the target when an
  admin deletes their account

`reminder_rules.template_key` was a hard FK to `email_templates.key`
in the single-key schema; once the PK became `(key, locale)` the FK
target was no longer unique, so the constraint was dropped in
`0005_email_template_per_locale` and the reference is now an
application-level soft FK enforced by the rule-CRUD API.

Invite + verification links are rendered from `settings.app_base_url`
— set this to the public URL on prod (`https://app.example.com`),
not `localhost`.

`MAIL_BACKEND` env auto-selects: `console` / `smtp` / `dummy`. Unset
falls back to `smtp` when `ENVIRONMENT=prod`, else `console`.

`send_and_log` and `enqueue_and_log` both accept `entity_type` +
`entity_id` so emails can be attributed to a domain row in
`email_log` without a hard FK.

## Account lifecycle

Two onboarding paths, one offboarding path. All three intersect with
the email pipeline + audit log.

**Onboarding A — invite (default):**

1. Admin creates a `user_invites` row with `role_codes: list[str]`.
2. The `invite` template is sent with the accept-link.
3. Invitee fills in password + name on `/accept-invite`. The User
   row is created, every role in `role_codes` is assigned, and
   `is_verified=True` (invites bypass email verification — clicking
   the link is the verification).
4. Login. Optional 2FA enrollment via the profile page.

**Onboarding B — self-serve signup** (only when `auth.allow_signup` is
on; off by default):

1. Visitor POSTs `/auth/register` with email + password + name.
2. `services.signup.register_user` creates the User + assigns
   `auth.signup_default_role_code` + writes an `email_verification`
   row + sends the `email_verify` template. SMTP failures are
   suppressed — the email_log captures the failure, the account
   creation succeeds.
3. Visitor clicks the link → `/verify-email` → POST
   `/auth/verify-email` with the token → `email_verified_at` is
   set. Token is sha256-hashed at rest, 24 h TTL, single-use.
4. Login. Refused with a "verify your email" message until step 3
   completes (when `auth.require_email_verification` is on).

**Offboarding — soft-delete + grace + hard-delete:**

1. POST `/users/me/delete` (self) or `/admin/users/{id}/delete`
   (admin with `user.manage`). The self-route requires the password
   in the body as a defence against unattended-tab attackers; the
   admin route doesn't (the admin already authed). The admin route
   refuses to delete a `super_admin`.
2. `services.account_deletion.soft_delete_user` anonymises PII in
   place (email → `deleted+<id>@invalid`, full_name →
   `"Deleted user"`, phone → null, hashed_password → ""), revokes
   every active `auth_sessions` row, sets `deleted_at = NOW()` and
   `scheduled_hard_delete_at = NOW() + auth.delete_grace_days`. The
   `account_delete_confirm` email goes out with the hard-delete
   date. Audit row records actor + reason.
3. Operator can reinstate during the grace window — there's no
   self-serve undelete (the password is already wiped).
4. The `account_hard_delete` worker handler scans for users whose
   `scheduled_hard_delete_at` has elapsed and deletes them outright.
   Cascades fan out via the FK definitions in `0001_atrium_init`
   (auth_sessions, notifications etc. CASCADE; audit_log.actor_user_id
   SET NULL so history survives with an anonymous actor).

When `auth.allow_self_delete` is False the self-delete route returns
404 (route-existence not broadcast). Same convention as
`/auth/register` when `allow_signup` is off.

## Scheduled jobs (handler registry + built-ins)

Atrium ships the queue plumbing **and three platform-owned
handlers**; everything domain-specific belongs in host apps.

Built-in handlers (registered by
`app.jobs.builtin_handlers.register_builtin_handlers` at worker
startup):

- `audit_prune` — daily DELETE on `audit_log` driven by
  `app_settings['audit'].retention_days`. `<= 0` is the "retain
  forever" sentinel.
- `email_send` — drains a single `email_outbox` row, see
  Email pipeline above.
- `account_hard_delete` — tick-driven scan of users whose
  `scheduled_hard_delete_at <= now`.

Host-app handlers register the same way:

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
UI. Fields: `name`, `template_key` (soft reference to
`email_templates.key` — the per-locale PK reshape in
`0005_email_template_per_locale` dropped the hard FK), `anchor`
(free-form string), `kind` (free-form string), `days_offset` (signed
int), `active`. Atrium ships **no** anchors or kinds — the host app
decides what they mean and writes the logic that turns a rule into
a `ScheduledJob` row.

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

## Audit log

`app.services.audit.record(...)` is the only place that writes
`audit_log`. Diff values are coerced to JSON-safe types by
`_json_safe` (dates, Decimals, Enums → strings).

When a super_admin is impersonating someone, the audit middleware
populates a ContextVar from the `atrium_impersonator` cookie and
`record(...)` reads it to set `audit_log.impersonator_user_id`.
That's how the audit trail distinguishes "target did X" from
"super_admin did X while impersonating target".

**Retention**: unbounded by default. To enable time-bounded retention,
write `app_settings['audit'] = {"retention_days": N}` (admin UI →
System tab) and the `audit_prune` job will DELETE older rows daily.
`N <= 0` is "retain forever".

## Backend conventions

- Async everywhere. Never mix sync `Session` with async routes.
- When an async handler needs to read a server-defaulted column
  (`created_at`, `updated_at`) on an object it just inserted, call
  `session.refresh(obj, attribute_names=["…"])`.
- Add new Alembic migrations under
  `backend/alembic/versions/YYYY_MM_DD_NNNN-*.py`. Keep the chain
  linear (never branch) and include both upgrade and downgrade.
  Current head: `0005_email_template_per_locale`.
- `B008` is silenced for `fastapi.Depends`, `fastapi.Query`, etc. via
  `extend-immutable-calls`. Don't refactor `Depends(...)` calls to
  dodge the lint.
- `RUF001`/`RUF003` flag ambiguous unicode (em-dash, typographic
  quotes) — use ASCII hyphens in source. Markdown is freer; still
  prefer ASCII for diff-sanity.
- Middleware that talks to the DB must use
  `app.db.get_session_factory()`, not FastAPI DI — see
  `MaintenanceMiddleware`. Tests rebind that via the autouse
  `_bind_middleware_to_test_engine` fixture.

## Frontend conventions

- Mantine v9 only. Dark mode uses Mantine's color scheme attribute.
- Theme is composed in `src/theme/ThemedApp.tsx`: base theme +
  selected `preset` from `src/theme/presets/` + `brand.overrides`
  from `/app-config`. The frontend re-renders through MantineProvider
  whenever the brand config changes.
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
- The `/app-config` public bundle is fetched once at boot and held in
  a TanStack query; `useAppConfig` reads from it. The admin UI hits
  `/admin/app-config` which returns every namespace. Translation
  overrides from `i18n.overrides[locale]` are merged on top of the
  bundled JSON resources at i18next init.
- `preferred_language` lives on the User row and is exposed via
  `/users/me`; the profile page picker writes it back. i18next syncs
  to it on save.
- CKEditor 5 is loaded from the CDN (see `index.html`); the
  `VITE_CKEDITOR_LICENSE_KEY` is injected via Vite HTML
  `%VITE_*%` substitution. Set it to `GPL` to use the free tier.
- Host bundles inject UI fragments via the registry in
  `src/host/registry.ts`: `registerHomeWidget`, `registerRoute`,
  `registerNavItem`, `registerAdminTab`, `registerProfileItem`. All
  five must be called at import-time before React mounts (see
  `loadHostBundle` in `src/main.tsx`). `registerProfileItem` takes an
  optional `slot` (`after-profile` / `after-password` / `after-2fa` /
  `after-roles` (default) / `after-sessions` / `before-delete`) and an
  optional `condition({ me })` predicate; the host owns the card
  chrome (no auto-wrapping in a `Paper`).

## Testing

- **Backend**: `make test-backend` runs pytest against MySQL 8
  (testcontainers in dev, a GitHub Actions service on CI). The
  session fixture TRUNCATEs after every test but preserves
  `app_settings`, `email_templates`, and `permissions` (those are
  invariant across tests). `roles` + `role_permissions` ARE truncated
  and re-seeded per test (`_reseed_rbac`) because admin tests
  legitimately mutate them. The `_bind_middleware_to_test_engine`
  autouse fixture wipes `app_settings['system']` after every test so
  a stuck maintenance flag doesn't 503 the rest of the suite.
- **Frontend**: `pnpm test` = vitest unit tests. `pnpm playwright
  test` = Playwright specs.
- **Smoke**: `make smoke` brings up the e2e stack (prod web image via
  `docker-compose.e2e.yml`), seeds an admin, and runs the Playwright
  suite. Run before pushing anything that touches auth, the app
  shell, the login flow, or the admin app-config tabs.
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
    |  TLS
    v
edge proxy (your firewall)             <- terminates public TLS
    |  TLS (self-signed origin)
    v
proxy (nginx:alpine, :9443)            <- this repo; trusts XFF from edge
    |  HTTP (docker network)
    +- /api/*  ->  api  (FastAPI on :8000, rewrite strips /api)
    +- /*      ->  web  (nginx:alpine serving built dist)
            |
            +- mysql + worker inside the same compose
```

`infra/proxy/gen-cert.sh` generates a self-signed cert at first boot
into the `atrium_proxy_certs` volume — stable across restarts, wipe
the volume to rotate. `set_real_ip_from 10/8,172.16/12,192.168/16`
means the proxy trusts the edge's `X-Forwarded-For`, so the backend
sees the real client IP.

### Config

- `.env` is the only env-var surface. `docker-compose.yml` reads it
  via `env_file`. Compose v2 expands `${VAR}` inside `.env`, so the
  DSN can reference `${MYSQL_USER}` etc.
- Runtime knobs live in the `app_settings` table — see
  **App configuration** above.
- The frontend bundle is built with `VITE_API_BASE_URL=/api`
  (relative). One image works regardless of which hostname the
  browser arrived on — handy when you hit the VM directly for
  testing on `:9443`.

### First deploy on a new box

See `README.md` -> **Prod** for the exact sequence. After editing
`.env` on a running stack you must `docker compose … up -d
--force-recreate api worker` — env is captured at container start,
never re-read. Changes made through `/admin/app-config` take effect
without a restart (subject to the maintenance-mode 2 s cache TTL).

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
9. **`MaintenanceMiddleware` bypasses FastAPI DI.** It reads
   `app.db.get_session_factory()` directly so it can run before any
   request-scoped dependency resolves. Tests must rebind the factory
   to the testcontainers engine — that's what the autouse
   `_bind_middleware_to_test_engine` fixture does. Don't add new
   middleware that talks to the DB without applying the same
   pattern.
10. **`app_settings` is a TRUNCATE-skip table in tests.** A row
    written by one test will leak into the next unless explicitly
    cleared. The conftest autouse now wipes both `system` (the
    maintenance flag) and `auth` (the captcha provider + password
    policy) between tests; for any other namespace you mutate,
    reset it in the test's teardown.
11. **`CaptchaLoginMiddleware` reads `auth.captcha_provider` on
    every gated request.** It hits the DB through
    `get_session_factory()` (no DI), so tests that flip the provider
    must clean up — same shape as the maintenance flag. The
    autouse cleanup in the conftest covers it.
12. **The maintenance-flag cache TTL is 2 seconds.** Tests that flip
    the flag and immediately hit a route must call
    `maintenance.reset_cache()` — otherwise the previous read still
    wins. The Playwright maintenance spec sleeps briefly for the
    same reason.
13. **`auth.allow_signup` and `auth.allow_self_delete` return 404
    when off, not 403.** Don't accidentally "fix" this — the route's
    existence shouldn't be broadcast on tenants that haven't opted
    in.
14. **`app_settings` namespaces have no migration to seed them.**
    Defaults come from the Pydantic model; the row materialises on
    first PUT. Don't write Alembic seed migrations for new
    namespaces — bump the model and let `model_validate` apply
    defaults on read.

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
