# Atrium ↔ host compat matrix

A host on (e.g.) `0.10.0` planning the jump to `0.12.0` reads this page once
and knows: no migrations to coordinate, four new optional registry hooks
became available along the way, the SSE wire format changed in `0.11.3`,
the registry's `element:` shape on `registerRoute` / `registerAdminTab` is
soft-deprecated in favour of `render()`. Release notes carry the prose; the
matrix below is the navigation aid.

Your running atrium version is mirrored onto `window.__ATRIUM_VERSION__`
(available since 0.14.0 — see the *Runtime version detection* section in
[`published-images.md`](published-images.md)). Find that row in the table,
then read forward to plan the upgrade path.

## Matrix

| Atrium | Schema (alembic head) | New registry hooks | Deprecations | Env / config |
| ------ | --------------------- | ------------------ | ------------ | ------------ |
| [0.9.x](https://github.com/brendanbank/atrium/releases/tag/v0.9.1) | `0005_email_template_per_locale` (initial published chain) | `registerHomeWidget`, `registerRoute`, `registerNavItem`, `registerAdminTab`; backend `init_app` / `init_worker` contract; `seed_permissions` / `seed_permissions_sync` | — | new: `ATRIUM_HOST_MODULE` |
| [0.10.0](https://github.com/brendanbank/atrium/releases/tag/v0.10.0) | unchanged | — | — | new: `ATRIUM_STATIC_DIR`. **Breaking image change**: `atrium-backend` + `atrium-web` collapsed into one `atrium` image. Hosts must drop the separate `web` service and the proxy's `/api` rewrite, and bake their host SPA bundle into `/opt/atrium/static/host` |
| 0.11.0 | unchanged | `registerProfileItem` | — | — |
| [0.11.1](https://github.com/brendanbank/atrium/releases/tag/v0.11.1) | unchanged | `registerHomeWidget({ width })` opt-out; defensive Proxy on `window.__ATRIUM_REGISTRY__` so unknown `register*` calls log + no-op instead of throwing | — | — |
| [0.11.2](https://github.com/brendanbank/atrium/releases/tag/v0.11.2) | unchanged | `registerNotificationKind` | — | — |
| [0.11.3](https://github.com/brendanbank/atrium/releases/tag/v0.11.3) | unchanged | `subscribeEvent`. **SSE wire-format change**: `/notifications/stream` events now carry the row's actual `{kind, payload}` instead of the literal `{kind: 'refresh'}` | — | — |
| [0.12.0](https://github.com/brendanbank/atrium/releases/tag/v0.12.0) | unchanged | `registerLocale`; `render()` form on `registerRoute` and `registerAdminTab`; `roles[]` (role codes) added to `/admin/users` responses | `element:` shape on `registerRoute` / `registerAdminTab` is soft-deprecated — keep working via fallback, but new code should pass `render: () => …` | — |
| [0.14.0](https://github.com/brendanbank/atrium/releases/tag/v0.14.0) | unchanged | `__ATRIUM_VERSION__` on `window` for runtime feature detection; `HostForeignKey()` + `emit_host_foreign_keys` for cross-base FKs; typed `HostWorkerCtx.register_job_handler()` for `init_worker(host)`; published host SDK packages (`@brendanbank/atrium-host-{types,bundle-utils,test-utils}`); `__atrium_t__('common.*')` shared i18n keys; `npx @brendanbank/create-atrium-host` scaffolder | — | — |
| [0.14.1](https://github.com/brendanbank/atrium/releases/tag/v0.14.1) | unchanged | — (fix: `__ATRIUM_VERSION__` actually populates on the published image; v0.14.0 returned `"unknown"` because `atrium-backend` had no dist-info in the runtime venv — see #57) | — | — |
| [0.15.0](https://github.com/brendanbank/atrium/releases/tag/v0.15.0) | unchanged | — | — | **Breaking registry move**: image is now `ghcr.io/brendanbank/atrium` (was `ghcr.io/brendan-bank/atrium`); host SDK packages renamed `@brendan-bank/atrium-*` → `@brendanbank/atrium-*`. Hosts must update `ATRIUM_IMAGE` pins, `.npmrc` scope (`@brendanbank:registry=…`), and every `@brendanbank/atrium-*` import. The old `@brendan-bank/*` packages and `ghcr.io/brendan-bank/atrium` image have been deleted from the `Brendan-Bank` org — any host still pointing at the old paths will fail to pull / install. |
| [0.15.1](https://github.com/brendanbank/atrium/releases/tag/v0.15.1) | unchanged | — | — | **Host SDK packages moved to npmjs.org** (closes #70). `@brendanbank/atrium-host-types`, `…-host-bundle-utils`, `…-test-utils`, and `create-atrium-host` are now anonymous-readable on the public npm registry — no `.npmrc` scope mapping, no `read:packages` PAT, no token in CI / Dockerfile / compose. Hosts adopting 0.15.1+ should drop the `@brendanbank:registry=https://npm.pkg.github.com` line from their `.npmrc`. v0.15.0 packages remain on GitHub Packages (no impact on existing pinned consumers). |
| [0.15.2](https://github.com/brendanbank/atrium/releases/tag/v0.15.2) | unchanged | — | — | **Fixes silent RBAC breakage in 0.15.1** (closes #72). `useMe()` from `@brendanbank/atrium-host-bundle-utils/react` defaulted to fetching `/api/users/me/context`, which 404s on the merged-image atrium (the SPA + API share an origin with no `/api` strip). `usePerm()` then default-denied every code, silently disabling RBAC in hosts that adopted the package default. The fetcher now hard-codes the same-origin `/users/me/context` path (it's atrium-fixed, not host-configurable). **Breaking prop removal**: `<AtriumProvider>`'s `apiBase` prop is gone — hosts pinning `^0.15` will get a TypeScript error on `<AtriumProvider apiBase="…">` after the upgrade and should drop the prop. |
| [0.15.3](https://github.com/brendanbank/atrium/releases/tag/v0.15.3) | unchanged | `atrium:locationchange` CustomEvent on `window` whenever atrium's react-router commits a new location; `useAtriumLocation()` hook in `@brendanbank/atrium-host-bundle-utils/react` wraps it in `useSyncExternalStore` so host components observe in-place navigations (closes #77) | — | — |
| [0.16.0](https://github.com/brendanbank/atrium/releases/tag/v0.16.0) | `0006_email_outbox_perm` (seeds the `email_outbox.manage` permission, grants to `super_admin` + `admin`) | optional `order?: number` field on `NavItem` / `AdminTab` / `ProfileItem` for menu ordering across host + built-in items (closes #79); admin Email outbox tab + `GET /admin/email-outbox` + `POST /admin/email-outbox/{id}/drain` endpoints; `app.host_sdk.email.drain_outbox_row()` for host-side "send now" buttons (closes #80); `atrium:locationchange` event detail gains a monotonic `nonce` field, notification href clicks force-fire even when react-router would no-op, and `useAtriumNavigate()` exported from `@brendanbank/atrium-host-bundle-utils/react` for host-side URL cleanup that keeps atrium's router synced (closes #81) | — | — |
| [0.16.1](https://github.com/brendanbank/atrium/releases/tag/v0.16.1) | unchanged | — (fix: `EmailOutboxAdmin` polls every 8 s with `refetchIntervalInBackground: false` so drained rows update live without an operator hard-refresh — closes #83) | — | — |
| [0.17.0](https://github.com/brendanbank/atrium/releases/tag/v0.17.0) | unchanged | optional `section?: 'admin' \| 'settings'` on `registerAdminTab` for picking which expandable sidebar group the tab lands in (default `'admin'`); optional `setBuiltinAdminTabSection(key, section, order?)` so a host can relocate atrium's built-in admin tabs (`branding`, `emails`, `outbox`, `reminders`, `translations`, `system`, `auth`, `users`, `roles`, `audit`) into the Settings group and re-rank them | the horizontal `Tabs.List` strip on `/admin` is gone — each section is now a real route at `/admin/<key>` or `/settings/<key>`. Pre-0.17 `?tab=key` URLs redirect for one release, so existing bookmarks keep working. The CKEditor email-template editor is replaced with a Mantine-themed Tiptap (`RichTextField`); `VITE_CKEDITOR_LICENSE_KEY` env var and `cdn.ckeditor.com` CSP allowances removed | env: drop `VITE_CKEDITOR_LICENSE_KEY` from any host `.env` / Compose / CI build-args — atrium no longer reads it. CSP: hosts that mirrored atrium's `script-src https://cdn.ckeditor.com` should remove that allowance |
| [0.18.0](https://github.com/brendanbank/atrium/releases/tag/v0.18.0) | unchanged | `atrium:userchange` CustomEvent on `window` whenever the signed-in user identity transitions (login / logout / impersonation start-stop / same-tab re-login); `useAtriumUser()` hook in `@brendanbank/atrium-host-bundle-utils/react` wraps it in `useSyncExternalStore` so host bundles can clear their own QueryClient when the user changes (closes #87). Atrium's built-in admin sidebar tabs (Users, Reminder Rules) now respect their `*.manage` permission and hide for users who don't hold it, matching the existing `registerAdminTab({ perm })` contract for host tabs (closes #86) | — | — |
| [0.19.0](https://github.com/brendanbank/atrium/releases/tag/v0.19.0) | unchanged | — | — | **Breaking: API moved to `/api/*`** (closes #89). Every JSON route atrium ships now lives under `/api/...` so the SPA owns un-prefixed URL space — without this split, a hard-reload of an SPA admin page (e.g. `/admin/audit`, `/admin/users`, `/admin/roles`) resolved to the API's JSON payload because the API route matched first and the SPA static fallback only fires on 404. Host migration: (1) **backend routers** must use `prefix="/api/<your-pkg>/..."` (atrium does NOT auto-prefix host routers — the host owns its full path); (2) **frontend fetches** must call `/api/<your-pkg>/...`; (3) **Dockerfile** bake `VITE_API_BASE_URL="/api"` (was `""`); (4) **`@brendanbank/atrium-host-bundle-utils/react`'s `useMe()`** now hits `/api/users/me/context` automatically (no host change needed if you're on the SDK package — bump to 0.19.x); (5) any handwritten healthcheck curling `/healthz` should curl `/api/healthz`. The `/admin/...` URL space (e.g. `/admin/users`, `/admin/audit`, `/admin/roles`) is now SPA-owned, so host bundles registering admin tabs there work correctly on hard reload for the first time. **0.19.0 image is broken** — see 0.19.1. |
| [0.19.1](https://github.com/brendanbank/atrium/releases/tag/v0.19.1) | unchanged | — | — | **Fixes the broken 0.19.0 image** (closes #91). The 0.19.0 publish workflow's `build-args:` block carried over an empty `VITE_API_BASE_URL=` from the pre-prefix era, which silently overrode the Dockerfile's new `/api` default. The shipped SPA bundle was built with no API base URL and called every endpoint un-prefixed; against a 0.19.0 backend (where every route lives under `/api/...`) those calls fell through to the SPA fallback and returned `index.html`, so the login form never rendered and downstream Playwright suites timed out. 0.19.1 sets the build arg correctly and adds a post-build verification step that fails the publish job if the bundle doesn't contain the `/api` prefix string, so this regression cannot recur silently. **Hosts on 0.19.0: bump the image pin to `0.19.1` (or `0.19`).** No host code changes needed — the backend routing was already correct in 0.19.0; only the published image's frontend bundle was broken. |
| [0.19.2](https://github.com/brendanbank/atrium/releases/tag/v0.19.2) | unchanged | — | — | **Fixes maintenance-mode UX after the `/api/*` move.** The 0.19.0 maintenance middleware bypass list only carved out `/api/*` paths, so SPA HTML/asset requests at the root were 503'd: a maintenance-on browser received the JSON `{"detail":"maintenance",...}` body instead of the SPA, and the SPA's own `MaintenancePage` component never had a chance to render. 0.19.2 lets non-`/api/*` requests through the gate unconditionally — the SPA loads, fetches `/api/app-config` (still on the bypass list), reads `system.maintenance_mode`, and renders the friendly maintenance page client-side. Also: `app_config.put_namespace` now invalidates the maintenance middleware's 2 s in-process cache when the `system` key is written, so an admin flipping `maintenance_mode: false` propagates immediately instead of waiting up to 2 s for the cache TTL to expire. No host code changes — pure backend fix. |
| 0.20.0 | unchanged | `atrium:colorschemechange` CustomEvent on `window` (with synchronous `window.__ATRIUM_COLOR_SCHEME__` mirror so host bundles that mount after the initial dispatch read the current value without waiting for an event); `useAtriumColorScheme()` hook in `@brendanbank/atrium-host-bundle-utils/react` wraps it in `useSyncExternalStore`. Host bundles pass the result to their own `<MantineProvider defaultColorScheme={…}>` so nested providers stop defaulting to `"light"` and produce a two-tone UI on systems set to dark mode (closes #96). The hook returns `"auto"` on pre-0.20 atrium images, matching the in-source `defaultColorScheme="auto"` workaround that hosts on older images already carry. The `create-atrium-host` template + `examples/hello-world` consume the hook out of the box. | — | — |
| 0.21.0 | unchanged | — (fixes: `document.title` mirrors `brand.name` from the public `/app-config` bundle so a renamed tenant no longer ships a literal `<title>Atrium</title>` (closes #99); the starter HomePage's `home.welcomeNamed` greeting auto-hides whenever a host has registered a home widget, matching the existing `home.intro` gate from #28 (closes #100)) | — | — |

A blank cell means "no change in this release on that axis". Schema rows
list the alembic head a host can rely on coexisting with — atrium owns
`alembic_version`, the host owns `alembic_version_app`, and the two heads
advance independently (see [`published-images.md`](published-images.md#migrations)).

## Schema changes since the first published image

The atrium chain stayed at `0005_email_template_per_locale` from the first
published image (0.9.1) through the entire 0.9.x → 0.15.x line. **0.16.0
is the first to advance the chain**: revision `0006_email_outbox_perm`
seeds a new permission (`email_outbox.manage`) and grants it to
`super_admin` + `admin`. No table shape changes — adopting it is a single
`alembic upgrade head` with no app-level coordination.

This is the column that changes most rarely; when it does (a new revision
on `backend/alembic/versions/`), the cell names the revision id so a host
author can read what tables / columns are involved before pinning past it.

## SSE wire format

One change since the contract debuted in 0.9.1:

- **0.11.3** — `/notifications/stream` events switched from
  `{kind: 'refresh'}` (a hardcoded literal that just told consumers to
  refetch) to `{kind, payload}` mirroring the notification row. Atrium's
  bell still refetches on every event regardless of kind, so existing
  hosts that wrote their own `EventSource` and ignored the body keep
  working. Any host that explicitly required `kind === 'refresh'` needs
  a one-line edit. New hosts use `subscribeEvent(kind, handler)` and let
  atrium own the connection.

## How this is maintained

One row per published `vX.Y.Z` release. The row is added in the same PR
that bumps `backend/pyproject.toml` and writes the GitHub release notes —
[`RELEASING.md`](../RELEASING.md) step 1.5 captures this as part of the
release-time documentation sweep. Cells stay terse: the table is for
navigation, the release notes are the source of truth.

When a release introduces something for a column that has never been used
before (e.g. the first env-var rename, the first deprecation), prefer
adding the row's prose to the matching release notes and keeping the
matrix cell to a one-line summary plus a link.
