# What's next

Forward-looking ideas for atrium. Not a backlog, not a roadmap — a
list of features a future maintainer should weigh against the
project's "platform layer only" charter before pulling them in. Bias
to shipping things that every host app would otherwise rebuild from
scratch; resist anything that's actually domain logic.

## Auth + identity

- ~~**Mandatory 2FA enrollment after first login.** Phase 3 didn't
  land. Add `auth.require_2fa_enrollment: bool` and gate the SPA
  with a `2fa_enrollment_required` 403 code, mirroring
  `totp_required`.~~ Landed 2026-04-26 as `auth.require_2fa_for_roles`
  (per-role list rather than a single bool — strictly more
  expressive). 403 carries `code: "2fa_enrollment_required"`.
- ~~**Password policy namespace.** Min length, character classes,
  breach-list lookup (haveibeenpwned k-anon API). Today the only
  floor is fastapi-users' default 8 chars in
  `services/signup.py`.~~ Landed 2026-04-26 as
  `app.services.password_policy` + the `password_*` fields on
  `AuthConfig`. HIBP lookup is fail-open with a 5 min cache.
- **Idle session timeout.** `auth_sessions` already carries
  `last_seen_at`-style data via the SSE stream; expire any session
  idle longer than `auth.idle_timeout_minutes`. JWT alone can't
  enforce this — has to land in the cookie -> `sid` lookup.
- **More 2FA providers.** SMS (out — telephone-number PII pile is a
  liability for a starter; let host apps wire Twilio if they want),
  WebAuthn passkey UI sugar (cross-device QR flow), backup codes
  (currently absent — a user who loses their phone *and* their
  WebAuthn credential is locked out).
- **Magic-link login.** Optional namespace toggle. Useful for
  low-friction tenants; complementary to email OTP.
- **OAuth / SSO providers.** Google, Microsoft, GitHub. fastapi-users
  has the wiring; atrium just needs a namespace + admin UI for the
  client IDs.

## API surface

- **API tokens / personal access tokens.** Long-lived bearer tokens
  scoped to a subset of the holder's permissions. Today the only
  way to call atrium from a script is to drive the cookie + 2FA
  flow.
- **Per-user API rate limits.** `AuthRateLimitMiddleware` exists for
  the auth endpoints; extend to a generic per-route + per-user
  limiter with overrides in app_config.
- **Outbound webhooks.** A namespace for webhook subscriptions
  (URL + secret + event filter), a `webhook_outbox` mirroring
  `email_outbox` (durable, retried, dead-letter), and a built-in
  handler that signs the body. Strong candidate — every host app
  needs this.
- **OpenAPI tag groups + SDK generation.** The OpenAPI doc is
  already published at `/docs`; a `make sdk` that runs
  openapi-typescript + openapi-python-client would save host apps a
  recurring chore.

## Email + notifications

- ~~**Multi-language email templates (Phase 11).** Add a `language`
  column to `email_templates` (or a sibling `email_template_locales`
  table), pick by user `preferred_language` at render time, fall
  back to `en`. Admin UI gains a per-locale tab. The `i18n` namespace
  already gates which locales are enabled.~~ Landed 2026-04-26 as
  `0005_email_template_per_locale` (composite `(key, locale)` PK,
  not a sibling table). nl / de / fr variants of every shipped
  template seeded; `email_outbox.locale` persists the variant so
  retries don't drift; `EmailTemplatesAdmin.tsx` has a per-locale
  SegmentedControl.
- **Email outbox admin UI.** The outbox + dead-letter table is
  already populated; expose a "queued / sending / dead" view with a
  manual retry button.
- **Per-kind notification formatters.** The bell is kind-agnostic
  today (host apps register a renderer). A built-in registry +
  i18n key convention would cut boilerplate.

## Operations

- **Audit log export / streaming.** Periodic CSV / JSON dump to S3
  for tenants whose retention policy says "keep forever, but not
  in MySQL".
- **Read-only "operator" role.** Like `admin` but stripped of
  mutation permissions — useful for support staff who need to see
  user state but not change it.
- **Background task observability.** `scheduled_jobs` has a
  `status` + `last_error`; surface a "stuck / dead" view in the
  admin UI alongside the audit log.
- **Health-check granularity.** `/readyz` currently aggregates
  api + db + worker. Split into per-component endpoints so a load
  balancer can shed traffic from one box without yanking the
  whole stack.

## Tenancy + theming

- **Multi-tenant strand.** Atrium today assumes a single tenant per
  deploy. A real multi-tenant story (tenant-scoped `app_settings`,
  tenant in JWT claims, RLS-style query filtering) is a rebuild,
  not a tweak — but worth pricing if a host app keeps reaching for
  it.
- **CSS variable export from BrandConfig.** The Mantine override
  dict is fine; for host apps that need to theme their own non-
  Mantine widgets, exposing the resolved palette as CSS variables
  (`--atrium-color-primary` etc.) on `<html>` would be nice.

## Testing

- ~~**End-to-end Playwright spec for self-serve signup.** Phase 2
  shipped without one. The maintenance / branding / i18n /
  account-deletion specs are all there; signup is the gap.~~ Landed
  2026-04-26 (commit `e2c1715`) — signup + email verification
  Playwright specs are in `tests-e2e/`. Companion specs for
  password policy, CAPTCHA, and email-template i18n landed in the
  same window.
- **Load test scaffolding.** A locust / k6 scenario hitting login +
  10 admin reads, parameterised by user count, would surface
  regressions in the SSE / event_hub / `auth_sessions` lookup hot
  paths.

## Documentation

- **Per-namespace operator playbook.** "When to flip
  `system.maintenance_mode`", "what `audit.retention_days` means
  legally", etc. Today this is vibes + the comments in
  `app_config.py`.
