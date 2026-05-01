# `@brendanbank/atrium-host-bundle-utils`

Runtime helpers, Vite preset, and React hooks for [atrium](https://github.com/brendanbank/atrium)
host bundles. Wraps the dual-tree mount pattern so a host's
`main.tsx` collapses to ~10 lines of registration calls.

```tsx
import {
  AtriumRegistry,
  makeWrapperElement,
} from '@brendanbank/atrium-host-bundle-utils';
import { MyWidget } from './MyWidget';

const reg = window.__ATRIUM_REGISTRY__ as AtriumRegistry;
reg.registerHomeWidget({
  key: 'my-card',
  render: () => makeWrapperElement(<MyWidget />),
});
```

## Installation

```bash
pnpm add @brendanbank/atrium-host-bundle-utils \
        @brendanbank/atrium-host-types
```

The package is published on the public npm registry. No `.npmrc`,
no auth token, no PAT. If you adopted atrium before v0.15.1 and
have an `@brendanbank:registry=https://npm.pkg.github.com` line in
your `.npmrc`, delete it — npmjs.org is the default registry.

## Three subpath entry-points

| Import                                                     | What you get                                               |
| ---------------------------------------------------------- | ---------------------------------------------------------- |
| `@brendanbank/atrium-host-bundle-utils`                   | `makeWrapperElement`, `mountInside`, `unmountInside`, types |
| `@brendanbank/atrium-host-bundle-utils/vite`              | `hostBundleConfig({ entry })` — returns a Vite config      |
| `@brendanbank/atrium-host-bundle-utils/react`             | `useMe`, `usePerm`, `useRole`, `useUserContext`, `<AtriumProvider>` |

## Vite preset

```ts
// vite.config.ts
import { hostBundleConfig } from '@brendanbank/atrium-host-bundle-utils/vite';

export default hostBundleConfig({ entry: 'src/main.tsx' });
```

The factory returns a complete Vite library-mode config: emits a
single `dist/main.js` that atrium's loader dynamic-imports, inlines
imported `.css` via runtime `<style>` tags, and defines
`process.env.NODE_ENV` so the externalised React + TanStack Query
references resolve. Pass `extraConfig` to layer additional plugins
or overrides on top.

`vite` and `vite-plugin-css-injected-by-js` are declared as optional
peer deps; install them as devDependencies in the host's
`frontend/package.json` only when building the bundle.

## React hooks

```tsx
import {
  AtriumProvider,
  useMe,
  usePerm,
  useRole,
} from '@brendanbank/atrium-host-bundle-utils/react';

function CommissionsPage() {
  const { data: me, isLoading } = useMe();
  const hasPerm = usePerm();
  if (isLoading) return <Loader />;
  if (hasPerm('commission.view.all')) return <Admin />;
  return <SelfCommissions userId={me?.id} />;
}

function App() {
  return (
    <QueryClientProvider client={hostQueryClient}>
      <AtriumProvider>
        <CommissionsPage />
      </AtriumProvider>
    </QueryClientProvider>
  );
}
```

The hooks fetch atrium's fixed same-origin `/api/users/me/context`
endpoint (atrium >= 0.19) — no path is configurable, since a host
bundle loads inside atrium's SPA and hits the same origin. `<AtriumProvider>` reads from
your existing `<QueryClientProvider>` by default — no second
QueryClient. Pass `client={hostQueryClient}` to wrap one inline; pass
`fetchUserContext={...}` to inject a custom fetcher (useful for tests
or hosts that want axios-shaped retry).

## Versioning

The package version tracks atrium's image version. Pin `^0.23` for
"compatible with atrium 0.23.x"; bump together with the atrium image
to pick up new registry slots and SDK helpers.

## See also

- [`@brendanbank/atrium-host-types`](../host-types/) — the typed
  registry declarations this package re-exports.
- [`docs/published-images.md`](../../docs/published-images.md) — the
  full host-extension contract.
- [`examples/hello-world/`](../../examples/hello-world/) — the
  canonical worked example exercising every extension slot through
  these helpers.
