# `@brendanbank/atrium-host-types`

TypeScript declarations for the [atrium](https://github.com/brendanbank/atrium)
host-extension contract.

```ts
import type {
  AtriumRegistry,
  AtriumNotification,
  AtriumEvent,
  UserContext,
  AdminUserRow,
} from '@brendanbank/atrium-host-types';

const reg = window.__ATRIUM_REGISTRY__ as AtriumRegistry;
reg.registerHomeWidget({ key: 'my-card', render: () => /* ... */ });
```

The package is **types-only** — no runtime, no JS payload at runtime.
Bundlers strip it from the production output.

## Installation

The package is published on **GitHub Packages**, not the public npm
registry. Add an `.npmrc` to your host project that points the
`@brendanbank` scope at GitHub Packages:

```
# .npmrc
@brendanbank:registry=https://npm.pkg.github.com
```

GitHub Packages requires an authenticated install even for public
packages — give npm a token with at least the `read:packages` scope:

```
//npm.pkg.github.com/:_authToken=${GITHUB_TOKEN}
```

In CI, `GITHUB_TOKEN` is provided automatically by Actions; locally,
generate a [classic PAT](https://github.com/settings/tokens) with
`read:packages` and export it. Then:

```bash
pnpm add -D @brendanbank/atrium-host-types
```

## Versioning

The package version tracks atrium's image version. Pin `^0.14` for
"compatible with atrium 0.14.x"; bump together with the atrium image
to pick up new registry slots. New slots land as **optional** members
on `AtriumRegistry` first so a host that hasn't bumped yet still
type-checks.

## What ships

- `AtriumRegistry` — every `register*` slot atrium exposes plus
  `subscribeEvent`.
- `UserContext` — `/users/me/context` shape.
- `AdminUserRow` — `/admin/users` row shape.
- `AtriumNotification` — notification row body.
- `AtriumEvent` / `AtriumEventHandler` — SSE typed event shape.
- Per-slot option-bag types: `HomeWidget`, `RouteEntry`, `NavItem`,
  `AdminTab`, `ProfileItem`, `NotificationKindRenderer`,
  `LocaleOverlay`.
- `ProfileSlot`, `HomeWidgetWidth` — string unions.
- A `declare global` block that types `window.React`,
  `window.__ATRIUM_VERSION__`, and `window.__ATRIUM_REGISTRY__`.

## See also

- [`@brendanbank/atrium-host-bundle-utils`](../host-bundle-utils/) —
  runtime helpers, Vite preset, and React hooks. Re-exports the types
  from this package, so a host adding only one dep still gets the
  declarations.
- [`docs/published-images.md`](../../docs/published-images.md) — the
  full host-extension contract (image catalogue, loader behaviour,
  registry semantics).
- [`docs/compat-matrix.md`](../../docs/compat-matrix.md) — which
  atrium release added which slot.
