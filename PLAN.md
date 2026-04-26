# Atrium — extraction plan

Source: `/Users/brendan/src/booking-app-casa` (Casa Del Leone).
Target: `/Users/brendan/src/atrium`.

A reusable starter: auth (password + TOTP + email OTP + WebAuthn), invites,
RBAC + super-admin + impersonation, audit log, in-app notifications + SSE,
email templates + scheduled jobs engine, app-settings KV. React+Mantine
shell with the same auth/admin pages.

Legend: **MOVE** verbatim, **REFACTOR** (move but generalize), **STAY** in
Casa repo, **REBUILD** (don't copy file; rewrite cleaner).

---

## Status (auto-updated as work lands)

**Last touched:** 2026-04-26.

**Done (backend + infra):**
- Foundation refactors landed: `users.role` column dropped; `UserRole` enum gone; `UserInvite.role_codes: list[str]` (JSON column, multi-role at invite time); `ScheduledJob`/`EmailLog` use nullable `entity_type`+`entity_id` instead of `booking_id` FK.
- Auth helpers reshaped: `require_owner` retired across 8 routers in favour of `require_perm("…")`; `auth/scope.py` is now a no-op `AdminScope` skeleton; `auth/users.py` ships a convenience `require_admin` for the "admin role only" case.
- Service layer: `services/notifications.py` is a slim `notify_user(...)`; `services/visibility.py` deleted; `jobs/runner.py` is now a handler-registry engine; `jobs/schedule.py` is just `next_due_job`; `email/sender.py` takes `entity_type`+`entity_id`.
- API layer trimmed: `main.py` mounts only platform routers; `me_context.py` returns `roles: list[str]`; `admin_users.py` no longer imports `Booking`/`UserRole` and gates on `user.manage`; `invites.py` drops Agent eager-create; `admin_roles`/`audit`/`reminder_rules`/`email_templates` swapped to `require_perm`.
- Identity rename across cookies, audience tokens, contextvars, TOTP/WebAuthn issuer/RP-name, mail_from, settings DSN/passwords: `casa_*` → `atrium_*`.
- Alembic: fresh `0001_atrium_init.py` covering the full atrium schema + seeded permissions (8), roles (admin/super_admin/user), email templates (invite/password_reset/admin_password_reset_notice).
- Tests: `helpers.py` rewritten (`seed_admin`/`seed_super_admin`/`seed_user`); `test_invite_flow.py` and `test_notifications.py` deleted (atrium-specific replacements TODO); `conftest._reseed_rbac` uses atrium roles.
- Scripts: `seed_owner.py` → `seed_admin.py`; `db-dump.sh` decasaified; `infra/proxy/gen-cert.sh` CN default; nginx iframe block removed.
- Build: `Makefile` rewritten for atrium; `.env.example` rewritten; compose `casa_*` volumes/networks renamed; `pyproject.toml`/`package.json` names; FullCalendar deps dropped.

**Done (frontend):**
- App shell trimmed (`App.tsx` route table, `AppLayout.tsx` nav).
- `lib/types.ts`, `lib/auth.ts` use `roles: string[]` (RBAC role codes) instead of single `role`.
- `RequireAuth` accepts a free-form RBAC role-code prop.
- `UsersAdmin.tsx` invite modal uses MultiSelect bound to `role_codes: string[]`; user-edit form keeps the existing `role_ids: number[]` MultiSelect.
- `RemindersAdmin`/`AuditAdmin` use free-form text inputs for anchor/kind/entity (host apps fill in).
- `NotificationsBell`/`NotificationsPage` are kind-agnostic with a JSON-payload modal.
- `HomePage`, `ProfilePage`, `AdminPage` reshaped (no booking widgets, role-list display, perm-gated tabs).
- `i18n/locales/en.json` stripped of booking keys; `nl.json` is empty (i18next falls back to en).
- `tests-e2e/{smoke,email-otp,webauthn}.spec.ts` and `helpers.ts` updated (`atrium_auth` cookie; "Welcome"/"Profile" assertions).
- `index.html` title → "Atrium".

**Verification (2026-04-26 — all green):**
- Backend: `uv run python -c "from app.main import app"` — 67 routes registered, no import errors.
- Backend: `uv run ruff check .` — all checks pass.
- Backend: `uv run pytest` against testcontainers MySQL 8 — **81/81 passing** (60 inherited + 21 new).
- Backend: `alembic upgrade head` from a fresh DB succeeds (validated by the test session fixture).
- Frontend: `pnpm typecheck` (`tsc -b --noEmit`) — 0 errors.
- Frontend: `pnpm lint` — 0 errors, **0 warnings**.
- Frontend: `pnpm test` (vitest) — 6/6 passing.

**Adjustments made during verification:**
- `uv.lock` regenerated for the `atrium-backend` project name.
- Default seeded email templates extended with `email_otp_code` (the 2FA challenge email — backend's `email_otp.setup` requires it).
- Test passwords renamed from casa defaults: `owner-pw-123` → `admin-pw-123`, `agent-pw-123` → `user-pw-123`.
- Test role codes renamed: literal `"owner"` → `"admin"`, `"agent"` → `"user"` (in test_rbac_admin.py).
- Test email `"agent@example.com"` → `"user@example.com"` to match `seed_user` default.
- `admin_users.update` self-deactivate guard collapsed nested `if` into single (ruff SIM102).

**Cosmetic / nice-to-have items now addressed:**
- Fresh `test_invite_flow.py` written (12 cases — multi-role assignment, expired/revoked/already-accepted, 401/403 gates, password hashing).
- Fresh `test_notifications.py` written (9 cases — `notify_user` helper writes + publishes, scope isolation, mark-read idempotency, mark-all-read, delete, unread-only filter).
- React-hooks lint warnings (8) all resolved: 3 unused-disable directives auto-fixed; CKEditorField `react-hooks/refs` rule disabled with a documented "latest-callback pattern" comment; RolesAdmin `set-state-in-effect` disabled with a documented "alternative would be key-remount" comment; `renderNotificationBody` extracted to `frontend/src/lib/notifications.ts` to fix `react-refresh/only-export-components`.
- `AdminPage` Roles tab gate corrected: `usePerm('role.write')` → `usePerm('role.manage')` (the casa code typo from agent C — the Roles tab was invisible because no permission named `role.write` exists in atrium).
- `notifications.py` API docstring decasaified.

**E2E coverage extended:**
- `tests-e2e/invite-flow.spec.ts` — admin invites a user (via API for determinism), invitee accepts via the UI, redirect lands on `/login`, the API confirms the invite is `accepted_at != null` with the expected `role_codes`.
- `tests-e2e/logout.spec.ts` — verifies logout *effect*: `atrium_auth` cookie is dropped, protected route navigation bounces to `/login`. (Drives the API endpoint the UI button hits, since the avatar-menu trigger has no stable accessible name.)
- Existing specs (`smoke`, `email-otp`, `webauthn`) updated for atrium env-var names: `E2E_OWNER_*` → `E2E_ADMIN_*`, "owner" labels → "admin" — matches the renamed `Makefile` targets.

**UX fix during e2e shake-out:**
- Profile link was duplicated (left-nav `NavLink` *and* the user-menu under the avatar). Removed from the left nav; profile now lives only in the avatar dropdown. (Caught by the user; also unblocks the smoke spec's strict-mode locator.)
- `helpers.readLatestEmailOTPCodeFromLogs` regex relaxed to `/code is[:\s]*(\d{6})/i` so the seeded atrium `email_otp_code` template ("Your sign-in code is 123456") parses cleanly.
- Invite-accept spec selectors switched from `getByLabel(/password/i)` (which also matched Mantine's password-visibility toggle button) to the exact field labels.

**Makefile validated end-to-end:**
- `make help` ✅ clean
- `make test-backend` ✅ 81/81 via Make wrapping
- `make lint` ✅ ruff + eslint both clean
- `make test-frontend` ✅ vitest 6/6
- Compose-file `config --quiet` syntactically valid for both dev and e2e overlays.
- `make smoke` ✅ **5/5 Playwright specs pass** against the prod web image (smoke + email-OTP + webauthn + invite-flow + logout).

**Skipped (deemed harmless):**
- `ACTION_COLORS` map in audit UI still has `cancel: 'orange'` — useful for host apps that emit "cancel" actions; left in.
- `nl.json` empty placeholder — i18next falls back to `en`; already documented in CLAUDE.md.

**Status: pending commit (user requested no commit yet).**

---

## Status (auto-updated) — 2026-04-26 (Phases 0-11 round)

A second wave of work landed on top of the extraction baseline,
turning Atrium into a configurable platform rather than a
casa-shaped clone. What's in:

- **Phase 0 — app_config foundation.** Pydantic-namespace KV over
  `app_settings` (`backend/app/services/app_config.py`).
  `register_namespace(...)` lets later phases (and host apps) bolt on
  more without touching the route layer. Public namespaces are
  bundled by `GET /app-config`; admin namespaces by
  `GET /admin/app-config`. `auth.allow_signup` is the one carve-out
  exposed publicly so the LoginPage can render the signup link.
- **Phase 1 — branding + theming.** `BrandConfig` (name, logo,
  support email, preset, theme overrides). Three presets shipped:
  `default`, `dark-glass`, `classic` (`frontend/src/theme/presets/`).
  `ThemedApp.tsx` wires Mantine theme + brand into MantineProvider
  at boot. `BrandingAdmin.tsx` is the admin tab.
- **Phase 2 — self-serve signup + email verification.**
  `POST /auth/register` (rate-limited), `POST /auth/verify-email`.
  Token sha256-hashed at rest, 24 h TTL, single-use. Off by default
  (`auth.allow_signup=False`). `users.email_verified_at` gates login
  when `auth.require_email_verification=True`. Routes return 404
  when the feature is off so the route's existence isn't broadcast.
- **Phase 5 — maintenance mode + announcement banner.**
  `MaintenanceMiddleware` reads `system.maintenance_mode` from a
  2 s in-process cache, 503s everything except a small bypass list,
  passes super_admin cookies through. `AnnouncementBanner` reads
  `system.announcement` (plain text, max 2000 chars) +
  `announcement_level` (info / warning / critical).
  `MaintenancePage.tsx` is the route fallback when the cookie isn't
  super_admin.
- **Phase 6 — audit-log retention pruning.**
  `services/audit_retention.py` + `audit_prune` builtin handler.
  Retention is `app_settings['audit'].retention_days` (`<= 0` = keep
  forever). Single parameterised DELETE relying on MySQL `NOW() -
  INTERVAL`.
- **Phase 7 — account deletion (soft + grace + hard).**
  `services/account_deletion.py`. Self-route requires password
  reconfirm; admin route refuses on super_admin. Anonymises PII in
  place, revokes auth_sessions, schedules hard-delete by
  `auth.delete_grace_days`. `account_hard_delete` builtin handler
  drains the queue. CASCADE / SET NULL FK behaviour preserves audit
  history with an anonymous actor.
- **Phase 8 — durable email outbox.**
  `enqueue_and_log` mirrors `send_and_log` but inserts an
  `email_outbox` row + `queued` `email_log`. `email_send` builtin
  handler drains pending rows with exponential backoff (60 s, 5 m,
  30 m, 2 h, 12 h, dead-letter after 6 attempts). `[render failed]`
  / `[dead]` rows surface in the admin mail log.
- **Phase 9 — i18n broadening + Translations admin.** Three new
  bundled locales (de, fr) on top of en + nl. `I18nConfig`
  (`enabled_locales` + `overrides[locale][key]`). Frontend merges
  overrides on top of bundled resources at i18next init.
  `TranslationsAdmin.tsx` is the admin tab.
- **Phase 10 — per-user preferred_language.**
  `users.preferred_language` (varchar(5)). Profile page picker.
  `i18n.changeLanguage` syncs on save.
- **Phase 11 — multi-language email templates: NOT YET LANDED.**
  Email templates are still keyed by `key` only (no `language`
  column). Host apps that need per-locale variants currently use a
  key-naming convention (`invite`, `invite_nl`) or extend the table
  themselves. Tracked in `TODO.md`.

**Migrations added:** `0002_email_outbox`, `0003_user_soft_delete`,
`0004_email_verifications`. Head: `0004_email_verifications`.

**Default seeded email templates extended:** `email_verify`,
`account_delete_confirm`.

**E2E coverage extended:** `branding`, `i18n`, `maintenance`,
`account-deletion`, `profile-language`. All passing per the
respective phase commits.

**Skipped this round:**
- Phase 3 (mandatory 2FA enrollment after first login) — not landed.
  No `auth.require_2fa_enrollment` flag yet.
- Phase 4 / password policy — no `services/password_policy.py`. The
  fastapi-users default min-length-8 is the only floor.

---

## Backend — `backend/app/`

### Top level
| File | Action | Notes |
| --- | --- | --- |
| `__init__.py` | MOVE | |
| `db.py` | MOVE | |
| `logging.py` | MOVE | |
| `main.py` | REFACTOR | Trim router list to platform routers only. |
| `settings.py` | REFACTOR | Drop booking/iframe/property settings. |
| `worker.py` | MOVE | |

### `api/`
| File | Action | Notes |
| --- | --- | --- |
| `__init__.py` | MOVE | |
| `admin_roles.py` | MOVE | |
| `admin_users.py` | MOVE | |
| `audit.py` | MOVE | |
| `email_otp.py` | MOVE | |
| `email_templates.py` | MOVE | |
| `health.py` | MOVE | Drop booking/blocks probes from aggregate. |
| `impersonate.py` | MOVE | |
| `invites.py` | REFACTOR | Drop agent-eager-create + agent_id pre-link. |
| `me_context.py` | REFACTOR | Drop the `role` string field from `MeContext` (denormalised; replace with effective RBAC role codes). Otherwise verbatim. |
| `notifications.py` | MOVE | |
| `reminder_rules.py` | REFACTOR | Keep engine; drop booking-anchor defaults. |
| `sessions.py` | MOVE | |
| `totp.py` | MOVE | |
| `webauthn.py` | MOVE | |
| `agents.py` | STAY | |
| `blocks.py` | STAY | |
| `bookings.py` | STAY | |
| `calendar.py` | STAY | |
| `commission.py` | STAY | |
| `embed.py` + `embed_assets/` | STAY | |
| `payments.py` | STAY | |
| `seasons.py` | STAY | |

### `auth/`
All MOVE except `scope.py` → REFACTOR (drop `AgentScope`, keep an empty
`Scope` protocol + a no-op `AdminScope`).

### `email/`
| File | Action |
| --- | --- |
| `__init__.py` | MOVE |
| `backend.py` | MOVE |
| `sender.py` | MOVE |
| `templates/__init__.py` | MOVE |
| `notify_booking.py` | STAY |

### `jobs/`
All MOVE: `__init__.py`, `runner.py`, `schedule.py`, `types.py`.

### `models/`
| File | Action | Notes |
| --- | --- | --- |
| `__init__.py` | REFACTOR | Drop booking/property imports. |
| `auth.py` | MOVE | |
| `auth_session.py` | MOVE | |
| `email_otp.py` | MOVE | |
| `email_template.py` | MOVE | |
| `enums.py` | REFACTOR | Drop `Channel`, `BookingStatus`, `PrivateKind`, booking `RuleType`, booking anchors. Keep RBAC enums. |
| `mixins.py` | MOVE | |
| `ops.py` | REFACTOR | Holds Notification, ScheduledJob, EmailLog, AuditLog, AppSetting. Drop the `booking_id` FK from `ScheduledJob` and `EmailLog` — replace with nullable `entity_type` + `entity_id` if needed for cross-domain attribution. |
| `rbac.py` | MOVE | |
| `reminder_rule.py` | REFACTOR | Make `Anchor`/`RuleKind` host-extensible. |
| `user_totp.py` | MOVE | |
| `webauthn.py` | MOVE | |
| `agent.py` | STAY | |
| `blocked_range.py` | STAY | |
| `booking.py` | STAY | |
| `property.py` | STAY | |
| `season.py` | STAY | |

User model: keep, but drop `users.role` field (rely on RBAC).

### `schemas/`
MOVE: `__init__.py`, `audit.py`, `email_template.py`, `notification.py`, `reminder_rule.py`.
STAY: `agent.py`, `blocked_range.py`, `booking.py`, `commission.py`, `payment.py`, `season.py`.

### `services/`
| File | Action | Notes |
| --- | --- | --- |
| `__init__.py` | MOVE | |
| `audit.py` | MOVE | |
| `event_hub.py` | MOVE | |
| `html_sanitise.py` | MOVE | |
| `notifications.py` | REBUILD | This file *is* `notify_booking_event` — visibility-tier fanout for bookings. Write a fresh slim helper: `notify_user(session, user_id, kind, payload)` that writes the row and pokes `event_hub`. Booking fanout stays in Casa. |
| `rate_limit.py` | MOVE | |
| `totp.py` | MOVE | |
| `visibility.py` | REFACTOR | Generalize tier resolution; ship no built-in tiers. |
| `agent_codes.py` | STAY | |
| `booking_rules.py` | STAY | |
| `overlap.py` | STAY | |
| `pricing.py` | STAY | |
| `seasons.py` | STAY | |

### `scripts/`
| File | Action |
| --- | --- |
| `seed_owner.py` | REFACTOR → `seed_admin.py` |
| `seed_config.py` | STAY (heavily Casa: seasons, season-rules, blocked_ranges; reminder_rules + email_templates parts are reusable but interleaved). Atrium gets a fresh slim dump/load for email_templates + reminder_rules only. |
| `import_spreadsheet_2026.py` | STAY |

---

## Backend — `backend/alembic/versions/`

The chain is mixed. Squash platform migrations into a fresh `0001_atrium_init`
that reflects the final schema.

| Migration | Bucket |
| --- | --- |
| 0001 initial_schema | REBUILD (split: platform tables only) |
| 0002 commission_paid_at | STAY |
| 0003 email_templates_reminder_rules | REBUILD into 0001 |
| 0004 seed_dates_updated_template | STAY |
| 0005 seed_payment_recorded_template | STAY |
| 0006 seed_password_reset_template | REBUILD into 0001 (or 0002 seed) |
| 0007 rbac_roles_and_permissions | REBUILD into 0001 (trim perm set) |
| 0008 super_admin_and_impersonate | REBUILD into 0001 |
| 0009 booking_guest_language | STAY |
| 0010 grant_payment_perms_to_agent | STAY |
| 0011 seed_agent_plus_pii_role | STAY |
| 0012 booking_price_override | STAY |
| 0013 seed_admin_password_reset_notice_template | REBUILD into 0001 |
| 0014 audit_log_impersonator | REBUILD into 0001 |
| 0015 auth_sessions | REBUILD into 0001 |
| 0016 drop_is_superuser | REBUILD into 0001 |
| 0017 user_totp | REBUILD into 0001 |
| 0018 grant_price_override_to_agent_plus_pii | STAY |
| 0019 email_otp | REBUILD into 0001 |
| 0020 webauthn | REBUILD into 0001 |
| 0021 blocked_ranges | STAY |
| 0022 agent_referral_code | STAY |
| 0023 seed_partner_inquiry_templates | STAY |

Net atrium chain: `0001_atrium_init` + `0002_seed_default_email_templates`.

---

## Backend — `backend/tests/`

| Test | Action |
| --- | --- |
| `__init__.py`, `helpers.py` | MOVE (review helpers for booking refs) |
| `conftest.py` | REFACTOR (drop Casa seed, keep TRUNCATE keep-list logic) |
| `test_healthz.py` | MOVE |
| `api/test_email_otp.py` | MOVE |
| `api/test_impersonation.py` | MOVE |
| `api/test_invite_flow.py` | REFACTOR (drop agent eager-create assertions) |
| `api/test_notifications.py` | MOVE |
| `api/test_rbac_admin.py` | MOVE |
| `api/test_totp.py` | MOVE |
| `api/test_webauthn.py` | MOVE |
| `unit/test_mail_backend.py` | MOVE |
| `integration/test_scheduling.py` | STAY (every test seeds a Booking+Agent+Payment). Atrium needs new generic scheduling tests against a `noop_job` fixture. |
| `api/test_blocks.py` | STAY |
| `api/test_booking_stay_type_edit.py` | STAY |
| `api/test_bookings.py` | STAY |
| `api/test_bookings_visibility.py` | STAY |
| `api/test_embed.py` | STAY |
| `api/test_payments.py` | STAY |
| `api/test_payments_rbac.py` | STAY |
| `integration/test_block_overlap.py` | STAY |
| `integration/test_overlap.py` | STAY |
| `integration/test_reminder_emails.py` | STAY |
| `unit/test_booking_rules.py` | STAY |
| `unit/test_pricing.py` | STAY |
| `unit/test_visibility.py` | STAY |

---

## Frontend — `frontend/src/`

### Components
| File | Action |
| --- | --- |
| `App.tsx` | REFACTOR (route table) |
| `components/AppLayout.tsx` | REFACTOR (nav trims booking links) |
| `components/CKEditorField.tsx` | MOVE |
| `components/ImpersonationBanner.tsx` | MOVE |
| `components/InfoLabel.tsx` | MOVE |
| `components/NotificationsBell.tsx` | MOVE |
| `components/RequireAuth.tsx` | MOVE |
| `components/TwoFactorSetupModal.tsx` | MOVE |
| `components/admin/AuditAdmin.tsx` | MOVE |
| `components/admin/EmailTemplatesAdmin.tsx` | MOVE |
| `components/admin/RemindersAdmin.tsx` | REFACTOR (anchor list pluggable) |
| `components/admin/RolesAdmin.tsx` | MOVE |
| `components/admin/UsersAdmin.tsx` | MOVE |
| `components/Block*`, `Booking*`, `CalendarView.*`, `PaymentsSection.tsx` | STAY |
| `components/admin/{Agents,Commissions,RuleForm,SeasonForm,Seasons}Admin*` | STAY |

### Hooks
MOVE: `useAdmin`, `useAudit`, `useAuth`, `useEmailTemplates`,
`useNotificationStream`, `useNotifications`, `useReminderRules` (refactor),
`useRolesAdmin`, `useSessions`, `useTOTP`, `useUsersAdmin`, `useWebAuthn`.
STAY: `useBlocks`, `useBookings`, `useCommission`, `usePayments`.

### Lib
| File | Action |
| --- | --- |
| `lib/api.ts` | MOVE |
| `lib/auth.ts` | MOVE |
| `lib/queryClient.ts` | MOVE |
| `lib/theme.ts` | MOVE |
| `lib/types.ts` | REFACTOR (strip booking/agent/season types) |
| `lib/money.ts` (+ test) | MOVE (generic currency helper) |
| `lib/booking-validation.ts` (+ test) | STAY |
| `lib/pricing.ts` (+ test) | STAY |

### Routes
MOVE: `AcceptInvitePage`, `AdminPage` (refactor — trim tabs),
`ForgotPasswordPage`, `HomePage` (refactor — drop booking shortcuts),
`LoginPage`, `NotificationsPage`, `ProfilePage`, `ResetPasswordPage`,
`TwoFactorPage`.
STAY: `BookingsPage`, `CommissionsPage`, `SeasonsPage`.

### i18n / styles / entry / tests
MOVE: `i18n/index.ts` + locales (refactor — strip booking keys),
`main.tsx`, `styles/global.css`, `test/setup.ts`, `test/smoke.test.tsx`.

### E2e (`frontend/tests-e2e/`)
MOVE: `email-otp.spec.ts`, `helpers.ts`, `smoke.spec.ts`, `webauthn.spec.ts`.
STAY: `booking-flow.spec.ts`, `iframe-embed.spec.ts`.

---

## Root, infra, CI

| Path | Action | Notes |
| --- | --- | --- |
| `Makefile` | REFACTOR (drop seed-owner+booking targets) |
| `docker-compose.yml` | REFACTOR (drop iframe/property env) |
| `docker-compose.dev.yml` | MOVE |
| `docker-compose.e2e.yml` | MOVE |
| `docker-compose.override.yml` | MOVE |
| `.env.example` | REFACTOR (strip booking/property entries) |
| `.env` | NEVER COPY (real secrets) |
| `.gitignore` | MOVE |
| `.trivyignore` | MOVE |
| `infra/mysql/my.cnf` | MOVE |
| `infra/proxy/nginx.conf` | REFACTOR (drop `/embed/` + `/iframe/` location blocks) |
| `infra/proxy/gen-cert.sh` | MOVE |
| `frontend/{Dockerfile,nginx.conf,index.html,vite.config.ts,vitest.config.ts,playwright.config.ts,eslint.config.js,tsconfig.*,package.json,postcss.config.cjs}` | MOVE (refactor `package.json` name + deps) |
| `backend/{Dockerfile,pyproject.toml,uv.lock,alembic.ini}` | MOVE (refactor `pyproject` name) |
| `backend/alembic/{env.py,script.py.mako}` | MOVE |
| `.github/workflows/ci.yml` | MOVE |
| `.github/workflows/codeql.yml` | MOVE |
| `.github/workflows/uv-lock-refresh.yml` | MOVE |
| `scripts/` | review per file |
| `CLAUDE.md` | REBUILD (atrium-flavored, ~half the length) |
| `README.md` | REBUILD |
| `IFRAME.md` | STAY |
| `doc/` | STAY |
| `TODO.md` | drop (empty) |

---

## Refactor checklist (the bits that can't be a clean `cp`)

1. Drop `users.role` (`owner`/`agent`); rely on RBAC roles only.
2. Generalize `app/auth/scope.py`: ship a `Scope` protocol + no-op default; remove `AgentScope`.
3. `services/visibility.py`: extract a tier-resolution interface; ship no built-in tiers.
4. `models/reminder_rule.py` + `services` around it: anchors + rule-kinds become host-registered, atrium ships none.
5. `api/invites.py`: remove agent-eager-create + `agent_id` pre-link.
6. `api/me_context.py`: drop role-specific (booking) shape.
7. `api/health.py`: aggregate covers api + db + worker only (no booking probes).
8. `infra/proxy/nginx.conf`: delete the iframe block; keep the platform server-level CSP.
9. `Makefile`: drop `seed-owner`, booking smoke targets; rename to `seed-admin`.
10. `.env.example`: prune to auth/db/mail/webauthn/app-base-url.
11. Alembic: write a fresh `0001_atrium_init` reflecting the final platform schema; ship `0002_seed_default_email_templates` (invite, password reset, password reset admin notice, 2fa enrolled, account locked).
12. CLAUDE.md + README.md: rewrite for atrium.

---

## Execution order

1. `git clone booking-app-casa atrium-staging` (preserves history; we'll filter-branch later if we want a clean log). Or: `git init` here and copy in chunks.
2. Delete domain code top-down: iframe → calendar/booking-validation → bookings/blocks/seasons API + models → agent code → property → seeded booking templates/rules.
3. Apply the refactor checklist above.
4. Squash alembic into `0001_atrium_init` + `0002_seed_default_email_templates`.
5. Rewrite CLAUDE.md and README.md.
6. Smoke: `make smoke` should pass with login → 2FA → invite → role admin → notification.
