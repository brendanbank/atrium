# ADR 0002 — Host frontend SDK packaging (`@brendanbank/atrium-host-types`, `@brendanbank/atrium-host-bundle-utils`)

Status: accepted, 2026-04-28 (publish target amended 2026-04-29 — see addendum)

## Context

Atrium ships a host-extension contract on the frontend today
(`window.__ATRIUM_REGISTRY__`, the dual-tree wrapper-element pattern,
the `/users/me/context` endpoint), but every host re-implements the
same boilerplate at module init:

- `makeWrapperElement(child)` / `mountInside(el, child)` — extracted
  by hand into each host's `main.tsx`. Includes the child-mismatch
  unmount logic from #31, which surfaced as a real-world bug.
- An `interface AtriumRegistry { … }` block redeclared verbatim in
  every host. When atrium adds a registry method (e.g.
  `subscribeEvent?` in 0.11.3, `registerLocale` later) every host's
  declaration drifts.
- A Vite library-mode config + `vite-plugin-css-injected-by-js` recipe
  copy-pasted across hosts.
- A bespoke `useMe()` / `usePerm()` shape on top of TanStack Query
  that wraps `/users/me/context`.

Casa's `frontend/src/main.tsx` and `examples/hello-world/frontend/src/main.tsx`
each carry their own variant of the above. They drift over time.

Issues #37 (`@brendanbank/atrium-host-bundle-utils`), #38
(`@brendanbank/atrium-host-types`),
and #40 (`useMe`/`usePerm`/`useUserContext` hooks) close that gap.
This ADR records the packaging shape we land them in. It is the
frontend-side counterpart to ADR 0001 (`app.host_sdk` namespace for
Python helpers).

## Decision

### Packaging shape — in-tree pnpm workspace overlay

Two npm packages live in a new top-level `packages/` directory:

- `packages/host-types/` → published as `@brendanbank/atrium-host-types`
- `packages/host-bundle-utils/` → published as `@brendanbank/atrium-host-bundle-utils`

A repo-root `pnpm-workspace.yaml` includes `packages/*` and
`examples/hello-world/frontend` so the example consumes the packages
via `workspace:*` references. **Atrium's own `frontend/` is not in the
workspace.** It keeps its standalone `pnpm-lock.yaml` so the existing
Dockerfile (`COPY frontend/package.json frontend/pnpm-lock.yaml*`) and
the dev-container `node_modules` volume stay untouched. The atrium
SPA does not consume the published packages — it owns the registry
implementation that the packages declare against.

We considered:

- **Sibling repo per package** — gives independent release cadence
  but creates three places to keep aligned. Rejected: the packages
  are tightly coupled to atrium's release; the version sync becomes
  a chore.
- **One sibling monorepo** — same coupling, plus a new repo to stand
  up. Rejected for the same reason and the friction of cross-repo PRs.
- **In-tree monorepo with everything in one workspace** (atrium
  frontend + packages + example) — cleaner end-state but invasive:
  forces a Dockerfile rewrite, dev-container volume restructure, and
  Makefile adjustments for one release. Rejected as out of scope for
  this PR; a future ADR can pull the atrium frontend in once we have
  room to land the operational changes alongside.

### Publish target — GitHub Packages, `@brendanbank` scope

> **Amended 2026-04-29** — superseded by the addendum at the bottom
> of this ADR. The packages now publish to **npmjs.org** via Trusted
> Publishing. Original reasoning kept verbatim below for context.

Same registry family as `ghcr.io/brendanbank/atrium` for the runtime
image. One account/PAT covers both. Publishing happens from the same
release pipeline (see Consequences for the workflow shape).

The scope is `@brendanbank` (matching the GitHub owner) rather than
the more readable `@atrium` because GitHub Packages enforces
`scope == owner` for npm publishes. The published name pattern is
`@brendanbank/atrium-<area>` so the relationship to atrium stays
visible in the import path. Public-npm registration of a bare
`@atrium` scope was attempted and refused (existing `atrium` /
`atrium-*` packages on npmjs.com flagged it as confusable); GitHub
Packages keeps the namespace under our control and avoids the
trademark-adjacent friction.

### Versioning — tracks atrium

Both packages bump their version in lockstep with
`backend/pyproject.toml` on every release. A consumer pinning `^0.14`
of `@brendanbank/atrium-host-types` implies "compatible with atrium
`0.14.x` runtime image". This makes the compat matrix
(`docs/compat-matrix.md`, #46) trivial — one semver column covers
both the image and the SDK. The packages are 0.x today; pre-1.0
semver allows a minor bump to introduce additive slot changes without
coordinating a major.

The ADR explicitly does **not** introduce changesets / a release
tool yet. Versions are bumped by hand alongside the existing
`RELEASING.md` step 1.5 doc sweep.

### Subpath exports

`@brendanbank/atrium-host-bundle-utils` ships three subpath exports:

- `.` — runtime helpers (`makeWrapperElement`, `mountInside`,
  `unmountInside`) plus type re-exports from
  `@brendanbank/atrium-host-types` so a host needing only the
  runtime can `import` from one place.
- `./vite` — `hostBundleConfig({ entry })` factory. Imported only by
  `vite.config.ts` so it doesn't drag Vite into the host's runtime
  bundle.
- `./react` — `useMe`, `usePerm`, `useRole`, `useUserContext`,
  `<AtriumProvider>`. React is a peer dep on this entry only.

`@brendanbank/atrium-host-types` is a single types-only entry — `.d.ts` files
under `dist/`, no JS, no runtime cost. `react` is a peer dep so
`ReactElement` references resolve in the consumer's tree.

### What stays out of scope

- The `useMe`/`usePerm` hooks call the same `/users/me/context`
  endpoint atrium's own `useMe` does, but with their own TanStack
  Query cache. We do **not** try to share atrium's QueryClient — the
  cache lifetimes are different (atrium clears on logout via
  `qc.clear()`; the host's QueryClient is owned by the host bundle).
  `<AtriumProvider>` accepts an optional `client` so a host can opt
  in to wrapping their existing one, otherwise hooks pick up the
  caller's enclosing `<QueryClientProvider>`.
- We are not migrating casa from this PR. Casa's repo opens its own
  PR after the packages publish.
- We are not shipping a `startStream` / `EventSource` helper. Atrium
  already owns the connection and exposes `subscribeEvent` via the
  registry; a runtime helper would duplicate it.

## Consequences

- The `packages/` tree introduces a new workspace at the repo root.
  `pnpm -r build`, `pnpm -r typecheck`, and `pnpm -r test` operate on
  the SDK packages and the example only; atrium's own frontend
  continues to use its in-folder pnpm scripts.
- Future host-facing UI helpers land under `packages/host-bundle-utils`
  (or a sibling `packages/<area>` if the surface grows beyond the
  bundle entry-point) without another ADR. The "is this host-facing?"
  test is the same as ADR 0001: would a host import it?
- The publish step is added to `RELEASING.md` once the publish
  workflow is wired up. Until then the packages can be pulled into
  hosts via `pnpm pack` + a tarball install, which is enough for the
  in-tree example.
- `examples/hello-world/frontend/src/main.tsx` collapses from ~180
  lines to ~50 lines (mostly the registration calls themselves);
  `vite.config.ts` becomes one `hostBundleConfig({ entry })` call.
  The shrink is the load-bearing acceptance signal — if a future
  registry change blows that surface back out, the package is
  carrying less weight than it should.

## Addendum 2026-04-29 — switch publish target to npmjs.org

Issue #70 surfaced the limitation that prompted this amendment:
GitHub Packages' npm endpoint requires authentication on every
install, regardless of the package's stated visibility. A consumer
of `@brendanbank/atrium-host-types` therefore needs a `read:packages`
PAT in `.npmrc`, plumbed through CI, plumbed through the
`compose up --build` build context — which contradicted the
"public package" framing in the package READMEs and the scaffolder's
`.npmrc` template, and turned out to be enough adoption tax that
casa-bookings bailed out of consuming the package directly.

The switch:

- All four packages (`@brendanbank/atrium-host-types`,
  `atrium-host-bundle-utils`, `atrium-test-utils`, `create-atrium-host`)
  now publish to **npmjs.org**. Truly anonymous `pnpm add` works.
- Bootstrap-publish was done from a maintainer laptop with
  interactive 2FA at v0.15.0; future releases run via npm
  **Trusted Publishing** (OIDC) configured per package on npmjs.com.
  The publish workflow gains `permissions: id-token: write` and
  drops the `NODE_AUTH_TOKEN` env. No long-lived `NPM_TOKEN` is
  stored in the repo, and each tarball carries a signed provenance
  attestation tying it to the exact commit + workflow run.
- The original `@atrium`-scope-collision concern from the rejected
  alternatives still holds; we did not attempt to claim `@atrium` on
  npmjs.org. The published name pattern (`@brendanbank/atrium-<area>`)
  is unchanged.
- The v0.15.0 packages on GitHub Packages stay where they are
  (deletion isn't possible without contacting support, and there are
  no known external consumers). The READMEs, scaffolder template,
  `docs/published-images.md`, and `RELEASING.md` are updated to
  reflect npmjs.org as the canonical home; existing consumers who
  bumped to 0.15.1+ pick up the registry change by removing the
  `@brendanbank:registry=…` line from their `.npmrc`.
