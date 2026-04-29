// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * React hooks + provider for atrium host bundles.
 *
 * One TanStack Query subscription serves the whole host tree:
 * `useMe()` fetches `/users/me/context` once and shares the result
 * with every `usePerm()`, `useRole()`, and `useUserContext()` caller.
 * The hooks read the API base URL from `<AtriumProvider>` (default
 * `'/api'`) so a host serving its bundle on a different prefix can
 * point them at the right origin without forking the package.
 *
 * The hooks reuse the host's enclosing `<QueryClientProvider>` if one
 * is already mounted; pass `client={hostQueryClient}` to
 * `<AtriumProvider>` only if you want this provider to wrap the
 * QueryClient too. Two QueryClients (atrium's + the host's) is the
 * intended state — atrium clears its cache on logout via `qc.clear()`,
 * and a shared client would lose host queries the user still wants.
 */
import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useMemo,
  type ReactNode,
} from 'react';
import {
  QueryClientProvider,
  useQuery,
  type QueryClient,
  type UseQueryResult,
} from '@tanstack/react-query';

import type { UserContext } from '@brendanbank/atrium-host-types';

export type { UserContext } from '@brendanbank/atrium-host-types';
export { __atrium_t__ } from '../i18n';

interface AtriumContextValue {
  apiBase: string;
  fetchUserContext: () => Promise<UserContext | null>;
}

const DEFAULT_API_BASE = '/api';

async function defaultFetchUserContext(
  apiBase: string,
): Promise<UserContext | null> {
  const res = await fetch(`${apiBase}/users/me/context`, {
    credentials: 'include',
    headers: { Accept: 'application/json' },
  });
  if (res.status === 401 || res.status === 403) return null;
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`/users/me/context: ${res.status} ${body}`.trim());
  }
  return (await res.json()) as UserContext;
}

const AtriumContext = createContext<AtriumContextValue | null>(null);

export interface AtriumProviderProps {
  /** API base URL the hooks prefix on every fetch. Default `'/api'` —
   *  matches atrium's convention of mounting the API behind `/api/*`
   *  on the same origin as the SPA. */
  apiBase?: string;
  /** Optional TanStack QueryClient. When supplied the provider wraps
   *  children in a `<QueryClientProvider>`; otherwise the hooks
   *  inherit the caller's enclosing one. Use this only when the host
   *  hasn't already set up its own provider. */
  client?: QueryClient;
  /** Override the fetcher for `/users/me/context`. Useful for tests
   *  and for hosts that want to layer an axios interceptor or extra
   *  headers on top. The default uses `fetch` with `credentials:
   *  'include'`. */
  fetchUserContext?: () => Promise<UserContext | null>;
  children: ReactNode;
}

/** Provider that supplies `apiBase` and (optionally) a QueryClient
 *  to the atrium hooks below. Hosts that already wrap their tree in
 *  `<QueryClientProvider>` can omit `client` — the hooks use the
 *  caller's existing QueryClient. */
export function AtriumProvider({
  apiBase = DEFAULT_API_BASE,
  client,
  fetchUserContext,
  children,
}: AtriumProviderProps) {
  const value = useMemo<AtriumContextValue>(() => {
    const fetcher = fetchUserContext ?? (() => defaultFetchUserContext(apiBase));
    return { apiBase, fetchUserContext: fetcher };
  }, [apiBase, fetchUserContext]);

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
// override the API base or the fetcher. Lazily-allocated so the
// import has no side effects.
let DEFAULT_CTX: AtriumContextValue | null = null;
function defaultCtx(): AtriumContextValue {
  if (!DEFAULT_CTX) {
    DEFAULT_CTX = {
      apiBase: DEFAULT_API_BASE,
      fetchUserContext: () => defaultFetchUserContext(DEFAULT_API_BASE),
    };
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
