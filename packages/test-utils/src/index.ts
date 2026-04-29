// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Vitest helpers for unit-testing atrium host bundles.
 *
 * Atrium loads a host bundle by setting ``window.__ATRIUM_REGISTRY__``
 * and ``window.React`` and then ``await import()``-ing the bundle.
 * Hosts that test components touching that surface have to fake the
 * registry by hand — most casa tests today reach for Playwright
 * instead, which is much slower and more brittle.
 *
 * This package installs the fakes once per test:
 *
 *  - ``mockAtriumRegistry({ me })`` — installs a recording fake on
 *    ``window.__ATRIUM_REGISTRY__``, mirrors atrium's
 *    ``subscribeEvent`` semantics with an in-memory bus, exposes
 *    React via ``window.React`` (re-using the host's copy — atrium
 *    uses a single shared React in production), and stubs
 *    ``window.__atrium_i18n__`` so ``__atrium_t__`` calls resolve
 *    against an English fallback bundle. Returns handles so the test
 *    can assert against what the import-time side-effects registered.
 *  - ``renderWithAtrium(ui)`` — wraps ``@testing-library/react``'s
 *    ``render`` with a fresh ``QueryClient`` + ``<AtriumProvider>``
 *    pre-wired to return the configured ``me``. Returns the standard
 *    ``RenderResult`` so existing assertions work unchanged.
 *  - ``fireAtriumEvent(kind, payload)`` — dispatches a synthetic
 *    event the same way atrium's SSE stream would. Subscribers
 *    registered via the fake registry's ``subscribeEvent`` see it.
 *
 * Peer deps only — vitest, @testing-library/react, react,
 * @tanstack/react-query are the host's, not bundled. The package
 * provides the seam, not the framework.
 */
import {
  createElement,
  type ComponentType,
  type ReactElement,
  type ReactNode,
} from 'react';
import * as ReactNS from 'react';
import {
  QueryClient,
  QueryClientProvider,
} from '@tanstack/react-query';
import { render, type RenderOptions, type RenderResult } from '@testing-library/react';

import {
  AtriumProvider,
  type UserContext,
} from '@brendanbank/atrium-host-bundle-utils/react';
import type {
  AdminTab,
  AtriumEvent,
  AtriumEventHandler,
  AtriumRegistry,
  HomeWidget,
  LocaleOverlay,
  NavItem,
  NotificationKindRenderer,
  ProfileItem,
  RouteEntry,
} from '@brendanbank/atrium-host-types';

export type {
  AdminTab,
  AtriumEvent,
  AtriumEventHandler,
  AtriumRegistry,
  HomeWidget,
  LocaleOverlay,
  NavItem,
  NotificationKindRenderer,
  ProfileItem,
  RouteEntry,
  UserContext,
};

// ---------------------------------------------------------------------------
// Fake i18n — minimum surface __atrium_t__ reads via window.__atrium_i18n__
// ---------------------------------------------------------------------------

interface MinimalI18n {
  language?: string;
  t: (
    key: string,
    options?: Record<string, unknown> & { defaultValue?: string },
  ) => string;
}

function makeFakeI18n(
  resources: Record<string, Record<string, string>>,
  language: string,
): MinimalI18n {
  return {
    language,
    t(key, options) {
      const langs = [language, 'en'];
      for (const l of langs) {
        const hit = resources[l]?.[key];
        if (typeof hit === 'string') {
          return interpolate(hit, options);
        }
      }
      const def = options?.defaultValue;
      return typeof def === 'string' ? def : key;
    },
  };
}

function interpolate(
  s: string,
  vars?: Record<string, unknown> & { defaultValue?: string },
): string {
  if (!vars) return s;
  return s.replace(/\{\{(\w+)\}\}/g, (match, key) => {
    if (key === 'defaultValue') return match;
    const v = vars[key];
    return v == null ? match : String(v);
  });
}

// ---------------------------------------------------------------------------
// Module-level event bus
// ---------------------------------------------------------------------------

type Subscribers = Map<string, Set<AtriumEventHandler>>;

let activeSubscribers: Subscribers | null = null;

/** Dispatch an atrium SSE-style event to every handler the host
 *  subscribed via the fake registry. No-op when called outside a
 *  ``mockAtriumRegistry`` scope so a test that forgets to call
 *  ``mockAtriumRegistry`` first surfaces as an empty assertion rather
 *  than a TypeError. */
export function fireAtriumEvent(
  kind: string,
  payload: Record<string, unknown>,
): void {
  const subs = activeSubscribers;
  if (!subs) return;
  const handlers = subs.get(kind);
  if (!handlers || handlers.size === 0) return;
  const event: AtriumEvent = { kind, payload };
  // Snapshot so a handler that unsubscribes mid-fire doesn't skip a
  // sibling handler that's later in iteration order.
  for (const handler of [...handlers]) {
    handler(event);
  }
}

// ---------------------------------------------------------------------------
// Mock registry handles
// ---------------------------------------------------------------------------

/** Recorded registrations + reset/cleanup hooks returned by
 *  ``mockAtriumRegistry``. Tests assert against the array fields and
 *  call ``cleanup()`` from ``afterEach`` to drop the
 *  window globals back to their pre-mock state. */
export interface MockAtriumHandles {
  /** The fake registry installed on ``window.__ATRIUM_REGISTRY__``.
   *  Test bodies that want to call register methods directly (instead
   *  of through a host bundle's import-time side-effects) reach for
   *  this. */
  registry: AtriumRegistry;
  homeWidgets: HomeWidget[];
  routes: RouteEntry[];
  navItems: NavItem[];
  adminTabs: AdminTab[];
  profileItems: ProfileItem[];
  notificationKinds: NotificationKindRenderer[];
  localeOverlays: LocaleOverlay[];
  /** Drop every recorded registration + every event subscriber.
   *  Useful between tests inside the same ``describe`` that want to
   *  share the rest of the mock context. */
  reset(): void;
  /** Restore the pre-mock window state. Call from ``afterEach`` so
   *  the next test's ``mockAtriumRegistry`` starts from a clean
   *  baseline. */
  cleanup(): void;
}

export interface MockAtriumOptions {
  /** What ``useMe()`` resolves to. Pass ``null`` to simulate a
   *  signed-out user (atrium responded 401/403). Defaults to
   *  ``null``. */
  me?: UserContext | null;
  /** Locale resources the fake ``__atrium_t__`` resolves against.
   *  Keys are flat dot-paths (``'common.save'``); the outer key is
   *  the locale code. Defaults to a minimal English bundle covering
   *  the keys atrium ships in ``common.*``. Pass an empty object to
   *  exercise the missing-key fallback. */
  i18n?: {
    resources?: Record<string, Record<string, string>>;
    language?: string;
  };
}

interface SavedGlobals {
  registry: AtriumRegistry | undefined;
  React: unknown;
  i18n: unknown;
}

const DEFAULT_I18N_EN: Record<string, string> = {
  'common.save': 'Save',
  'common.cancel': 'Cancel',
  'common.delete': 'Delete',
  'common.edit': 'Edit',
  'common.new': 'New',
  'common.close': 'Close',
  'common.confirm': 'Confirm',
  'common.back': 'Back',
  'common.loading': 'Loading…',
  'common.empty': 'Nothing here yet.',
  'common.error': 'Something went wrong.',
  'common.search': 'Search',
  'common.required': 'Required',
  'common.language': 'Language',
};

function buildFakeRegistry(handles: MockAtriumHandles, subs: Subscribers): AtriumRegistry {
  return {
    registerHomeWidget(widget) {
      handles.homeWidgets.push(widget);
    },
    registerRoute(route) {
      handles.routes.push(route);
    },
    registerNavItem(item) {
      handles.navItems.push(item);
    },
    registerAdminTab(tab) {
      handles.adminTabs.push(tab);
    },
    registerProfileItem(item) {
      handles.profileItems.push(item);
    },
    registerNotificationKind(renderer) {
      handles.notificationKinds.push(renderer);
    },
    registerLocale(overlay) {
      handles.localeOverlays.push(overlay);
    },
    subscribeEvent(kind, handler) {
      let set = subs.get(kind);
      if (!set) {
        set = new Set();
        subs.set(kind, set);
      }
      set.add(handler);
      return () => {
        set?.delete(handler);
      };
    },
  };
}

/** Install a recording fake registry on ``window`` for the duration of
 *  a test. The handles returned record every register* call so tests
 *  can assert that a host bundle wired up the slots it claims to.
 *
 *  ```ts
 *  let handles: MockAtriumHandles;
 *  beforeEach(() => {
 *    handles = mockAtriumRegistry({
 *      me: {
 *        id: 1, email: 'alice@example.com', full_name: 'Alice',
 *        is_active: true, roles: ['admin'],
 *        permissions: ['hello.toggle'], impersonating_from: null,
 *      },
 *    });
 *  });
 *  afterEach(() => handles.cleanup());
 *
 *  test('host bundle registers a home widget', async () => {
 *    await import('../src/main');
 *    expect(handles.homeWidgets).toHaveLength(1);
 *    expect(handles.homeWidgets[0].key).toBe('hello-world');
 *  });
 *  ```
 *
 *  Side effects:
 *   - ``window.__ATRIUM_REGISTRY__`` is replaced with the fake.
 *   - ``window.React`` is set to the package's React copy so
 *     ``makeWrapperElement(...)`` calls resolve. Tests that need a
 *     specific React identity can override after the call.
 *   - ``window.__atrium_i18n__`` is set to a fake i18n with the
 *     bundled English ``common.*`` strings (override via the
 *     ``i18n`` option). */
export function mockAtriumRegistry(
  options: MockAtriumOptions = {},
): MockAtriumHandles {
  if (typeof window === 'undefined') {
    throw new Error(
      '[atrium-test-utils] mockAtriumRegistry requires a jsdom-style ' +
        'window — set vitest.environment to "jsdom" in vitest.config.ts',
    );
  }

  const w = window as unknown as {
    __ATRIUM_REGISTRY__?: AtriumRegistry;
    React?: unknown;
    __atrium_i18n__?: unknown;
  };

  const saved: SavedGlobals = {
    registry: w.__ATRIUM_REGISTRY__,
    React: w.React,
    i18n: w.__atrium_i18n__,
  };

  const subs: Subscribers = new Map();
  const handles: MockAtriumHandles = {
    registry: undefined as unknown as AtriumRegistry,
    homeWidgets: [],
    routes: [],
    navItems: [],
    adminTabs: [],
    profileItems: [],
    notificationKinds: [],
    localeOverlays: [],
    reset() {
      handles.homeWidgets.length = 0;
      handles.routes.length = 0;
      handles.navItems.length = 0;
      handles.adminTabs.length = 0;
      handles.profileItems.length = 0;
      handles.notificationKinds.length = 0;
      handles.localeOverlays.length = 0;
      subs.clear();
    },
    cleanup() {
      w.__ATRIUM_REGISTRY__ = saved.registry;
      w.React = saved.React;
      w.__atrium_i18n__ = saved.i18n;
      if (activeSubscribers === subs) {
        activeSubscribers = null;
      }
      subs.clear();
    },
  };

  handles.registry = buildFakeRegistry(handles, subs);

  w.__ATRIUM_REGISTRY__ = handles.registry;
  w.React = ReactNS;

  const i18nResources = options.i18n?.resources ?? { en: DEFAULT_I18N_EN };
  const language = options.i18n?.language ?? 'en';
  w.__atrium_i18n__ = makeFakeI18n(i18nResources, language);

  // Stash the configured ``me`` on a module-level slot so
  // ``renderWithAtrium`` can pass it through to AtriumProvider's
  // ``fetchUserContext`` override without each call site re-passing
  // it. Cleared by ``cleanup()`` via the activeSubscribers reset.
  configuredMe = options.me ?? null;

  activeSubscribers = subs;

  return handles;
}

// ---------------------------------------------------------------------------
// renderWithAtrium
// ---------------------------------------------------------------------------

let configuredMe: UserContext | null = null;

export interface RenderWithAtriumOptions extends RenderOptions {
  /** Override ``me`` for this single render. Useful for
   *  parameterised tests that vary the signed-in user without
   *  re-installing the registry. Falls back to the value from
   *  ``mockAtriumRegistry({ me })``. */
  me?: UserContext | null;
  /** Provide your own QueryClient — useful if the test asserts
   *  against cached data or invalidations. Defaults to a fresh client
   *  with retries disabled so a 401 surfaces immediately. */
  queryClient?: QueryClient;
  /** Wrap children in additional providers (MantineProvider,
   *  RouterProvider, etc.). Default: identity. */
  wrap?: ComponentType<{ children: ReactNode }>;
}

function makeTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

/** ``@testing-library/react``'s ``render`` pre-wired with a fresh
 *  QueryClient and ``<AtriumProvider>`` pointed at the configured
 *  ``me``. Returns the standard ``RenderResult`` so existing
 *  assertions (``getByRole``, ``rerender``, ``unmount``) work
 *  unchanged.
 *
 *  ```tsx
 *  test('owners see the per-agent picker', () => {
 *    const { getByLabelText } = renderWithAtrium(<CommissionsPage />);
 *    expect(getByLabelText('Agent')).toBeInTheDocument();
 *  });
 *  ```
 *
 *  Pass ``me`` to override the value from ``mockAtriumRegistry`` for
 *  a single render — handy in parameterised tests. Pass
 *  ``queryClient`` to share a client across renders so cache
 *  assertions survive the second mount. */
export function renderWithAtrium(
  ui: ReactElement,
  options: RenderWithAtriumOptions = {},
): RenderResult {
  const { me, queryClient, wrap, ...rest } = options;
  const client = queryClient ?? makeTestQueryClient();
  const meValue = me === undefined ? configuredMe : me;
  const Wrap = wrap;

  function Wrapper({ children }: { children: ReactNode }) {
    const inner = createElement(AtriumProvider, {
      fetchUserContext: async () => meValue,
      children,
    });
    const wrapped = Wrap ? createElement(Wrap, { children: inner }) : inner;
    return createElement(QueryClientProvider, { client, children: wrapped });
  }

  return render(ui, { wrapper: Wrapper, ...rest });
}
