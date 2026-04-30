# packages/ — published host SDK packages

Four npm packages plus their workspace lockfile. Each one publishes
on tag push via `.github/workflows/publish-npm.yml`.

## Version lockstep

**All four package.jsons must carry the same version, and that version
must match `backend/pyproject.toml`.** `publish-npm.yml` fans out to
every package on tag push — a stale version in any one blocks the
release. Use `make release-bump V=X.Y.Z` (top-level Makefile) which
calls `scripts/bump-version.sh` to bump everything in one shot rather
than editing the package.jsons by hand.

The intra-workspace deps use `workspace:*`, so the lockfile diff after
a bump shows up only in `pnpm-lock.yaml`'s `importers:` section. A
near-empty diff is expected.

## What each package contains

| Package                  | What's in it                                   | Hosts import it for                        |
| ------------------------ | ---------------------------------------------- | ------------------------------------------ |
| `host-types`             | TypeScript declarations only — `AtriumRegistry`, `UserContext`, `NavItem` / `AdminTab` / `ProfileItem`, `AtriumNotification`, `AtriumEvent`, `AtriumLocation`, `AtriumUserChangeDetail`, `AtriumColorScheme` / `AtriumColorSchemeChangeDetail`. | Type-checking host bundles against the registry contract. No runtime code. |
| `host-bundle-utils`      | Vite preset (`./vite`), React hooks (`./react` — `useMe` / `usePerm` / `useRole` / `useAtriumLocation` / `useAtriumNavigate` / `useAtriumUser` / `useAtriumColorScheme`), `__atrium_t__` i18n helper, the dual-tree mount pattern. | Building a host bundle: `main.tsx` ends up ~10 lines of `register*` calls. |
| `test-utils`             | Vitest helpers — fake `__ATRIUM_REGISTRY__` + `window.React`, working QueryClient, synthetic event bus mirroring `subscribeEvent`. | Unit-testing host components in isolation, no SPA boot. |
| `create-atrium-host`     | The `npx @brendanbank/create-atrium-host <name>` scaffolder. Emits backend Python package + frontend Vite bundle + compose stack + CI, all wired against atrium's published image and these SDK packages. | Bootstrapping a fresh host repo from scratch. |

`host-types` is the source-of-truth contract. New registry slots land
there first as **optional** members of `AtriumRegistry` so a host
pinned to an older version still type-checks; the slot becomes
required only after a release window closes.

## When you change one of them

Atrium's own SPA does NOT consume these packages — it uses the
in-tree `frontend/src/host/registry.ts` directly. The packages are
strictly for external host bundles. So:

- A type or shape change in `host-types/src/index.ts` must be
  mirrored in `frontend/src/host/registry.ts` (and vice versa). The
  two are kept in sync by hand; CI doesn't enforce it. Grep
  `frontend/src/host/registry.ts` for the related type when editing
  `packages/host-types/`.
- A change to `host-bundle-utils/src/react/index.ts` doesn't affect
  atrium's SPA — but `examples/hello-world/frontend/` consumes the
  packages via `workspace:*`, so the Hello World e2e test
  (`make smoke-hello`) IS affected. Run it before merging UI hook
  changes.
- A change to `create-atrium-host/template/` only affects newly
  scaffolded hosts. Existing hosts don't pull from the template;
  they consume the published packages.

## Publish flow

1. `git tag -s vX.Y.Z` and push → `publish-npm.yml` fires.
2. Each package's `pnpm publish` uses **npm Trusted Publishing** (OIDC
  against this workflow file) — no `NPM_TOKEN` secret, signed
  provenance attestations on every tarball.
3. `pnpm publish` is idempotent on identical version+content; if the
  workflow re-runs against an already-published version, pnpm reports
  "version already exists" and exits non-zero. Re-tag with a bumped
  version rather than forcing.

See `RELEASING.md` step 8 for the watch-and-confirm dance and
`docs/adr/0002-host-frontend-sdk-packaging.md` for why the packages
live in this repo (vs a separate one) and why they publish to npmjs
(vs GitHub Packages).
