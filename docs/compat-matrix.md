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

A blank cell means "no change in this release on that axis". Schema rows
list the alembic head a host can rely on coexisting with — atrium owns
`alembic_version`, the host owns `alembic_version_app`, and the two heads
advance independently (see [`published-images.md`](published-images.md#migrations)).

## Schema changes since the first published image

There have been **no atrium-side schema changes** since the first published
image (0.9.1). The chain has stayed at `0005_email_template_per_locale`
across the entire 0.9.x → 0.12.x line. A host's alembic chain that was
written against any of these images can upgrade to the latest without
coordinating an atrium migration.

This is the column that changes most rarely; when it does (a new revision
on `backend/alembic/versions/`), the cell will name the revision id and
link to the migration file so a host author can read what tables / columns
are involved before pinning past it.

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
