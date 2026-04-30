// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * React hooks + provider for atrium host bundles.
 *
 * One TanStack Query subscription serves the whole host tree:
 * `useMe()` fetches `/api/users/me/context` once and shares the
 * result with every `usePerm()`, `useRole()`, and `useUserContext()`
 * caller.
 *
 * The endpoint path is fixed by atrium — it's mounted under
 * `/api/...` (atrium >= 0.19) and served from the same origin as the
 * bundle. There's no `apiBase` prop because there's nothing for the
 * host to configure: a host bundle that loads inside atrium's SPA
 * fetches a same-origin relative path. Hosts that want to layer
 * their own retry / headers / mock can pass `fetchUserContext`.
 *
 * The hooks reuse the host's enclosing `<QueryClientProvider>` if
 * one is already mounted; pass `client={hostQueryClient}` to
 * `<AtriumProvider>` only if you want this provider to wrap the
 * QueryClient too. Two QueryClients (atrium's + the host's) is the
 * intended state — atrium clears its cache on logout via
 * `qc.clear()`, and a shared client would lose host queries the user
 * still wants.
 */
import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from 'react';
import {
  QueryClientProvider,
  useQuery,
  type QueryClient,
  type UseQueryResult,
} from '@tanstack/react-query';

import type {
  AtriumUserChangeDetail,
  UserContext,
} from '@brendanbank/atrium-host-types';

export type {
  AtriumUserChangeDetail,
  UserContext,
} from '@brendanbank/atrium-host-types';
export { __atrium_t__ } from '../i18n';

interface AtriumContextValue {
  fetchUserContext: () => Promise<UserContext | null>;
}

const ME_CONTEXT_PATH = '/api/users/me/context';

async function defaultFetchUserContext(): Promise<UserContext | null> {
  const res = await fetch(ME_CONTEXT_PATH, {
    credentials: 'include',
    headers: { Accept: 'application/json' },
  });
  if (res.status === 401 || res.status === 403) return null;
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`${ME_CONTEXT_PATH}: ${res.status} ${body}`.trim());
  }
  return (await res.json()) as UserContext;
}

const AtriumContext = createContext<AtriumContextValue | null>(null);

export interface AtriumProviderProps {
  /** Optional TanStack QueryClient. When supplied the provider wraps
   *  children in a `<QueryClientProvider>`; otherwise the hooks
   *  inherit the caller's enclosing one. Use this only when the host
   *  hasn't already set up its own provider. */
  client?: QueryClient;
  /** Override the fetcher for `/api/users/me/context`. Useful for
   *  tests and for hosts that want to layer an axios interceptor or
   *  extra headers on top. The default uses `fetch` with
   *  `credentials: 'include'`. */
  fetchUserContext?: () => Promise<UserContext | null>;
  children: ReactNode;
}

/** Provider that supplies the atrium hooks below with their fetcher
 *  and (optionally) a QueryClient. Hosts that already wrap their tree
 *  in `<QueryClientProvider>` can omit `client` — the hooks use the
 *  caller's existing QueryClient. */
export function AtriumProvider({
  client,
  fetchUserContext,
  children,
}: AtriumProviderProps) {
  const value = useMemo<AtriumContextValue>(
    () => ({ fetchUserContext: fetchUserContext ?? defaultFetchUserContext }),
    [fetchUserContext],
  );

  const inner = createElement(AtriumContext.Provider, { value }, children);

  if (client) {
    return createElement(QueryClientProvider, { client }, inner);
  }
  return inner;
}

/** Stable cache key for the `/users/me/context` query. Exported so
 *  hosts can `queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY })`
 *  after a flow that changed the user's roles or permissions. */
export const ME_QUERY_KEY = ['atrium', 'me'] as const;

// Module-level fallback so hooks work without an explicit
// `<AtriumProvider>` — convenient for hosts that don't need to
// override the fetcher. Lazily-allocated so the import has no side
// effects.
let DEFAULT_CTX: AtriumContextValue | null = null;
function defaultCtx(): AtriumContextValue {
  if (!DEFAULT_CTX) {
    DEFAULT_CTX = { fetchUserContext: defaultFetchUserContext };
  }
  return DEFAULT_CTX;
}

function useAtriumContextOrDefault(): AtriumContextValue {
  const ctx = useContext(AtriumContext);
  return ctx ?? defaultCtx();
}

/** Fetch the signed-in user's RBAC context. Returns the standard
 *  TanStack Query result so callers can surface loading and error
 *  states — `data` is `null` when the user is not signed in (atrium
 *  responded 401/403) and the typed `UserContext` otherwise.
 *
 *  Cache is shared with `usePerm` / `useRole` / `useUserContext` —
 *  one network request per host tree. Stale time is 60s, matching
 *  atrium's own `useMe` so the host's cache invalidation rhythm
 *  doesn't fight atrium's. */
export function useMe(): UseQueryResult<UserContext | null> {
  const { fetchUserContext } = useAtriumContextOrDefault();
  return useQuery<UserContext | null>({
    queryKey: ME_QUERY_KEY,
    queryFn: fetchUserContext,
    staleTime: 60_000,
    retry: false,
  });
}

/** Alias for `useMe()` — present because issue #40 documents both
 *  names. The shape is identical; pick whichever reads better at the
 *  call site. */
export function useUserContext(): UseQueryResult<UserContext | null> {
  return useMe();
}

/** Returns a stable predicate `(code) => boolean` over the signed-in
 *  user's permissions. While `useMe` is still loading or if the user
 *  is signed out, the predicate returns `false` for every code — so
 *  callers default to "not allowed" which is the safe fallback for
 *  RBAC gating.
 *
 *  Returning a function (not a boolean) is deliberate: a single
 *  call site can check several codes against one query subscription,
 *  matching the pattern in issue #40:
 *
 *  ```tsx
 *  const hasPerm = usePerm();
 *  if (hasPerm('commission.view.all')) return <Admin />;
 *  if (hasPerm('commission.view.own')) return <SelfCommissions />;
 *  ```
 */
export function usePerm(): (code: string) => boolean {
  const { data: me } = useMe();
  return useCallback(
    (code: string) => (me?.permissions ?? []).includes(code),
    [me?.permissions],
  );
}

/** Convenience: does the signed-in user hold the named role? Returns
 *  `false` while loading and when signed out, mirroring `usePerm`. */
export function useRole(code: string): boolean {
  const { data: me } = useMe();
  return (me?.roles ?? []).includes(code);
}

/** Snapshot of atrium's current router location, mirrored on
 *  `window.location`. The fields match react-router's `Location` shape
 *  so a host already familiar with `useLocation()` reads the same
 *  contract here. */
export type AtriumLocation = {
  pathname: string;
  search: string;
  hash: string;
  /** Monotonic per-event counter atrium increments on every
   *  `atrium:locationchange` dispatch. Use this in effect deps when
   *  the effect should re-run on every navigation event, including a
   *  re-click of the same href that react-router would otherwise
   *  no-op (e.g. clicking the same notification bell item twice — see
   *  atrium #81). Without it, `useEffect(…, [search])` stays put
   *  because `search` is structurally identical between the two
   *  events. Always present from atrium 0.16+; `0` on older images
   *  that don't dispatch a nonce. */
  nonce: number;
};

const ATRIUM_LOCATION_EVENT = 'atrium:locationchange';

const SSR_LOCATION: AtriumLocation = {
  pathname: '/',
  search: '',
  hash: '',
  nonce: 0,
};

// Module-level cache so `useSyncExternalStore.getSnapshot` returns a
// referentially-stable object across renders — re-creating it every
// call would cause React to tear-loop the subscriber. The cache is
// refreshed only when an `atrium:locationchange` event lands or, on
// the first read, lazily from `window.location`.
let cachedLocation: AtriumLocation | null = null;

function readWindowLocation(): AtriumLocation {
  if (typeof window === 'undefined') return SSR_LOCATION;
  return {
    pathname: window.location.pathname,
    search: window.location.search,
    hash: window.location.hash,
    // No event has been observed yet, so we have no atrium-supplied
    // nonce. Zero is the documented "no nonce yet" value.
    nonce: 0,
  };
}

function getLocationSnapshot(): AtriumLocation {
  if (cachedLocation === null) cachedLocation = readWindowLocation();
  return cachedLocation;
}

function getServerLocationSnapshot(): AtriumLocation {
  return SSR_LOCATION;
}

function subscribeLocation(onChange: () => void): () => void {
  if (typeof window === 'undefined') return () => {};
  const handler = (e: Event) => {
    const detail = (e as CustomEvent<Partial<AtriumLocation> | undefined>)
      .detail;
    if (
      detail &&
      typeof detail.pathname === 'string' &&
      typeof detail.search === 'string' &&
      typeof detail.hash === 'string'
    ) {
      cachedLocation = {
        pathname: detail.pathname,
        search: detail.search,
        hash: detail.hash,
        // ``nonce`` was added to the event detail in atrium 0.16
        // (#81). Older images dispatch the event without it; default
        // to 0 so the field is always a number.
        nonce: typeof detail.nonce === 'number' ? detail.nonce : 0,
      };
    } else {
      cachedLocation = readWindowLocation();
    }
    onChange();
  };
  window.addEventListener(ATRIUM_LOCATION_EVENT, handler);
  return () => window.removeEventListener(ATRIUM_LOCATION_EVENT, handler);
}

/** Subscribe to atrium's react-router location changes from inside a
 *  host bundle's React tree. Returns `{ pathname, search, hash, nonce }`
 *  — the first three mirror `window.location`; `nonce` is a monotonic
 *  counter atrium increments on every dispatch.
 *
 *  Bridges the `atrium:locationchange` CustomEvent atrium dispatches
 *  on `window` through `useSyncExternalStore`, so multiple subscribers
 *  in the same tree share one event listener and the snapshot is
 *  referentially stable when nothing changed.
 *
 *  ```tsx
 *  function FocusDrawer() {
 *    const { search } = useAtriumLocation();
 *    const focus = new URLSearchParams(search).get('focus');
 *    return focus ? <BookingDetail id={focus} /> : null;
 *  }
 *  ```
 *
 *  When you want the effect to re-run on **every** navigation event —
 *  including the same-URL re-click case (clicking the same notification
 *  bell item twice — atrium #81) — include `nonce` in the deps:
 *
 *  ```tsx
 *  function FocusDrawer() {
 *    const { search, nonce } = useAtriumLocation();
 *    useEffect(() => {
 *      const focus = new URLSearchParams(search).get('focus');
 *      if (focus) openDrawer(focus);
 *      // Without `nonce` here, React dedupes on `[search]` so a second
 *      // click of the same href doesn't re-open the drawer.
 *    }, [search, nonce]);
 *  }
 *  ```
 *
 *  Hosts that don't use React (or want to handle navigation outside a
 *  component) can subscribe directly:
 *  `window.addEventListener('atrium:locationchange', e => …)`. The
 *  event's `detail` carries the same `{pathname, search, hash, nonce}`
 *  shape.
 *
 *  Available on atrium 0.15.3+; `nonce` lands in 0.16+. On older atrium
 *  images the hook still works but only reflects the initial
 *  `window.location` (and `nonce` stays at 0). Hosts that need to
 *  support pre-0.15.3 atrium can read `window.__ATRIUM_VERSION__` and
 *  fall back to `useLocation()` from a wrapper that remounts on route
 *  swaps. */
export function useAtriumLocation(): AtriumLocation {
  return useSyncExternalStore(
    subscribeLocation,
    getLocationSnapshot,
    getServerLocationSnapshot,
  );
}

/** Programmatic navigate that works from inside a host bundle's React
 *  tree, where `useNavigate()` from react-router isn't available
 *  (atrium owns the router context; the host tree only meets atrium's
 *  at the wrapper element produced by `makeWrapperElement`).
 *
 *  Returns a stable `navigate(href, opts?)` function that updates the
 *  URL via `pushState` / `replaceState` and re-syncs atrium's
 *  react-router by dispatching a synthesized `popstate`. Atrium then
 *  fires its own `atrium:locationchange` so other host listeners
 *  observe the change.
 *
 *  The primary use case is **cleaning up a deep-link query param after
 *  the host has consumed it** — a flow that previously had no host-
 *  observable solution (a raw `history.replaceState` desyncs atrium's
 *  router from the browser URL). See atrium #81.
 *
 *  ```tsx
 *  function FocusDrawer() {
 *    const { search } = useAtriumLocation();
 *    const navigate = useAtriumNavigate();
 *    const focus = new URLSearchParams(search).get('focus');
 *    return focus ? (
 *      <Drawer
 *        opened
 *        onClose={() => {
 *          // Strip the param so a second click of the same bell item
 *          // (which navigates to the same href) is a real change from
 *          // atrium's perspective and re-fires the locationchange.
 *          const next = new URLSearchParams(search);
 *          next.delete('focus');
 *          navigate(`/?${next.toString()}`, { replace: true });
 *        }}
 *      >
 *        <BookingDetail id={focus} />
 *      </Drawer>
 *    ) : null;
 *  }
 *  ```
 *
 *  Available since atrium 0.16. The hook works on older images too —
 *  it doesn't depend on any atrium-side surface — but on pre-0.16 the
 *  resulting `atrium:locationchange` event won't carry a `nonce`. */
export function useAtriumNavigate(): (
  href: string,
  opts?: { replace?: boolean },
) => void {
  return useCallback((href: string, opts?: { replace?: boolean }) => {
    if (typeof window === 'undefined') return;
    if (opts?.replace) {
      window.history.replaceState(window.history.state, '', href);
    } else {
      window.history.pushState(window.history.state, '', href);
    }
    // React-router's BrowserHistory subscribes to ``popstate`` for
    // back/forward navigation. Synthesizing one here makes it re-read
    // ``window.location`` and update its internal state, which in turn
    // re-renders atrium's NavigationBridge and dispatches a fresh
    // ``atrium:locationchange`` with a new monotonic nonce.
    window.dispatchEvent(new PopStateEvent('popstate'));
  }, []);
}

/** Test-only: drop the cached snapshot so the next `getSnapshot` reads
 *  `window.location` fresh. Production code never calls this — the
 *  cache is updated by the event subscription. */
export function __resetAtriumLocationCacheForTests(): void {
  cachedLocation = null;
}

// ---------------------------------------------------------------------------
// Identity transitions — `atrium:userchange`
// ---------------------------------------------------------------------------

const ATRIUM_USERCHANGE_EVENT = 'atrium:userchange';

const NO_USERCHANGE: AtriumUserChangeDetail = {
  previous: null,
  current: null,
  nonce: 0,
};

// Module-level cache so `useSyncExternalStore.getSnapshot` returns a
// referentially-stable object across renders. Updated only when an
// `atrium:userchange` event lands; `null` until the first event.
let cachedUserChange: AtriumUserChangeDetail | null = null;

function getUserChangeSnapshot(): AtriumUserChangeDetail {
  return cachedUserChange ?? NO_USERCHANGE;
}

function getServerUserChangeSnapshot(): AtriumUserChangeDetail {
  return NO_USERCHANGE;
}

function subscribeUserChange(onChange: () => void): () => void {
  if (typeof window === 'undefined') return () => {};
  const handler = (e: Event) => {
    const detail = (
      e as CustomEvent<Partial<AtriumUserChangeDetail> | undefined>
    ).detail;
    if (
      detail &&
      (detail.previous === null || typeof detail.previous === 'number') &&
      (detail.current === null || typeof detail.current === 'number')
    ) {
      cachedUserChange = {
        previous: detail.previous,
        current: detail.current,
        nonce: typeof detail.nonce === 'number' ? detail.nonce : 0,
      };
      onChange();
    }
  };
  window.addEventListener(ATRIUM_USERCHANGE_EVENT, handler);
  return () => window.removeEventListener(ATRIUM_USERCHANGE_EVENT, handler);
}

/** Subscribe to atrium's identity transitions from inside a host
 *  bundle's React tree. Returns the most recent `atrium:userchange`
 *  detail — `{previous, current, nonce}` — or a zeroed sentinel
 *  (`{previous: null, current: null, nonce: 0}`) before any event has
 *  fired. The hook does NOT report the initial signed-in state on
 *  mount; use `useUserContext()` for that.
 *
 *  Bridges the `atrium:userchange` CustomEvent atrium dispatches on
 *  `window` through `useSyncExternalStore`, so multiple subscribers in
 *  the same tree share one event listener and the snapshot is
 *  referentially stable when nothing has changed.
 *
 *  The canonical use is wiping a host's own QueryClient when the user
 *  swaps — without it, user A's host cache renders for user B until
 *  staleness forces a refetch:
 *
 *  ```tsx
 *  function HostCacheGuard({ client }: { client: QueryClient }) {
 *    const { nonce } = useAtriumUser();
 *    useEffect(() => {
 *      // nonce > 0 means at least one transition has fired; on the
 *      // first paint we skip (the host already loaded against the
 *      // current user).
 *      if (nonce > 0) client.clear();
 *    }, [nonce, client]);
 *    return null;
 *  }
 *  ```
 *
 *  Hosts that don't use React (or want to clear the cache from outside
 *  any component) can subscribe directly:
 *  `window.addEventListener('atrium:userchange', () => client.clear())`.
 *
 *  Available on atrium 0.18+. On older atrium images the event is
 *  never dispatched, so the hook stays at the zeroed sentinel — host
 *  bundles that need to support pre-0.18 atrium can read
 *  `window.__ATRIUM_VERSION__` and fall back to the in-component
 *  watch-`useUserContext` workaround. */
export function useAtriumUser(): AtriumUserChangeDetail {
  return useSyncExternalStore(
    subscribeUserChange,
    getUserChangeSnapshot,
    getServerUserChangeSnapshot,
  );
}

/** Test-only: drop the cached snapshot so the next `getSnapshot`
 *  returns the zeroed sentinel. Production code never calls this — the
 *  cache is updated by the event subscription. */
export function __resetAtriumUserCacheForTests(): void {
  cachedUserChange = null;
}
