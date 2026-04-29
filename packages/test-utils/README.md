# `@brendanbank/atrium-test-utils`

Vitest helpers for unit-testing [atrium](https://github.com/brendanbank/atrium)
host bundles. Replaces hand-rolled mocks of `window.__ATRIUM_REGISTRY__`
+ `window.React` + `useMe()` so a host can render permission-gated
components and fire synthetic SSE events without spinning up the SPA.

## Why

Before this package, casa-style host tests had to wire mocks like:

```ts
beforeEach(() => {
  (window as any).__ATRIUM_REGISTRY__ = {
    registerHomeWidget: vi.fn(),
    /* …seven more vi.fn()s… */
    subscribeEvent: vi.fn(),
  };
  (window as any).React = require('react');
});
```

…and stub `useMe`'s underlying fetch separately. The seam is the same
in every host, so most teams skipped the unit tests and relied on
Playwright. This package gives them back.

## Installation

```
pnpm add -D @brendanbank/atrium-test-utils
```

The package is published on **GitHub Packages**, same scope as the
other atrium SDK packages — see the host-bundle-utils
[`README`](../host-bundle-utils/README.md) for the `.npmrc` setup.

`vitest`, `@testing-library/react`, `react`, `react-dom`, and
`@tanstack/react-query` are peer deps — install them once in your
host's `frontend/package.json`; this package will not bundle a
second copy.

## Usage

```tsx
import {
  fireAtriumEvent,
  mockAtriumRegistry,
  renderWithAtrium,
  type MockAtriumHandles,
  type UserContext,
} from '@brendanbank/atrium-test-utils';

const ALICE: UserContext = {
  id: 1, email: 'alice@example.com', full_name: 'Alice',
  is_active: true,
  roles: ['owner'],
  permissions: ['commission.view.all'],
  impersonating_from: null,
};

let handles: MockAtriumHandles;

beforeEach(() => {
  handles = mockAtriumRegistry({ me: ALICE });
});

afterEach(() => {
  handles.cleanup();
});

test('owners see the per-agent picker, not the self view', () => {
  const { getByLabelText } = renderWithAtrium(<CommissionsPage />);
  expect(getByLabelText('Agent')).toBeInTheDocument();
});

test('the host bundle registers a home widget on import', async () => {
  await import('../src/main');
  expect(handles.homeWidgets).toHaveLength(1);
  expect(handles.homeWidgets[0].key).toBe('commission-card');
});

test('refetches bookings on booking.created', async () => {
  renderWithAtrium(<BookingsPage />);
  fireAtriumEvent('booking.created', { booking_id: 42 });
  // …assert refetch fired
});
```

## API

### `mockAtriumRegistry(options?)`

Installs a recording fake on `window.__ATRIUM_REGISTRY__`, exposes
React via `window.React`, and stubs `window.__atrium_i18n__` with
the bundled `common.*` keys. Returns handles:

| Field                  | Type                          | Description                                           |
| ---------------------- | ----------------------------- | ----------------------------------------------------- |
| `registry`             | `AtriumRegistry`              | The fake (also at `window.__ATRIUM_REGISTRY__`).      |
| `homeWidgets`          | `HomeWidget[]`                | Recorded `registerHomeWidget` calls in order.         |
| `routes`               | `RouteEntry[]`                | Recorded `registerRoute` calls.                       |
| `navItems`             | `NavItem[]`                   | Recorded `registerNavItem` calls.                     |
| `adminTabs`            | `AdminTab[]`                  | Recorded `registerAdminTab` calls.                    |
| `profileItems`         | `ProfileItem[]`               | Recorded `registerProfileItem` calls.                 |
| `notificationKinds`    | `NotificationKindRenderer[]`  | Recorded `registerNotificationKind` calls.            |
| `localeOverlays`       | `LocaleOverlay[]`             | Recorded `registerLocale` calls.                      |
| `reset()`              | `() => void`                  | Drop registrations + subscribers, keep window mocks.  |
| `cleanup()`            | `() => void`                  | Restore pre-mock window state. Call in `afterEach`.   |

Options:

| Option              | Description                                                                  |
| ------------------- | ---------------------------------------------------------------------------- |
| `me`                | What `useMe()` resolves to. Pass `null` for signed-out. Default `null`.      |
| `i18n.resources`    | Locale → flat dot-path → string. Default: bundled English `common.*`.        |
| `i18n.language`     | Active locale. Default `'en'`.                                               |

### `renderWithAtrium(ui, options?)`

`@testing-library/react`'s `render` pre-wired with a fresh
`QueryClient` and `<AtriumProvider>` pointed at the configured `me`.
Returns the standard `RenderResult` so existing assertions
(`getByRole`, `rerender`, `unmount`) work unchanged.

Options extend the standard `RenderOptions` with:

| Option        | Description                                                              |
| ------------- | ------------------------------------------------------------------------ |
| `me`          | Override `me` for this render. Falls back to the registry default.       |
| `queryClient` | Share a client across renders so cache assertions survive remounts.      |
| `wrap`        | Additional wrapper component (e.g. `MantineProvider`, `RouterProvider`). |

### `fireAtriumEvent(kind, payload)`

Dispatches a synthetic SSE-style event to every handler the host
registered via the fake registry's `subscribeEvent`. No-op when
called outside a `mockAtriumRegistry` scope, so a forgotten setup
shows as an empty assertion rather than a crash.

## Versioning

Tracks `@brendanbank/atrium-host-bundle-utils`'s public API. When a
new registry slot lands in host-bundle-utils, the matching mock
shows up here in the next minor.

## See also

- [`@brendanbank/atrium-host-bundle-utils`](../host-bundle-utils/) — the
  runtime helpers + hooks this package mocks.
- [`@brendanbank/atrium-host-types`](../host-types/) — typed registry
  shapes.
- [`docs/published-images.md`](../../docs/published-images.md) — the
  full host-extension contract.
