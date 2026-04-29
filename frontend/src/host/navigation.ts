// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Atrium navigation bridge for host bundles.
 *
 * Host bundles live in their own React tree and don't share atrium's
 * react-router context (they only meet the atrium tree at the wrapper
 * `<div>` produced by ``makeWrapperElement``). That means a host can't
 * call ``useLocation()`` to observe atrium's programmatic navigations
 * — and ``popstate`` doesn't fire for ``history.pushState``, which is
 * what ``navigate(href)`` uses under the hood.
 *
 * To close the gap atrium dispatches an ``atrium:locationchange``
 * CustomEvent on ``window`` whenever its router commits a new location.
 * The detail payload mirrors ``window.location``: ``{pathname, search,
 * hash, nonce}``. ``nonce`` is a monotonic counter atrium increments on
 * every dispatch — hosts that want to re-run an effect on every
 * navigation event (including same-URL re-clicks like clicking the same
 * notification bell item twice — see #81) include ``nonce`` in their
 * effect deps. Hosts subscribe with a plain ``addEventListener`` (no
 * React coupling) or via the ``useAtriumLocation()`` hook in
 * ``@brendanbank/atrium-host-bundle-utils/react`` (which wraps the
 * event in ``useSyncExternalStore``).
 *
 * The bridge fires once on mount with the initial location too, so a
 * host that subscribes lazily (on its own component mount) doesn't need
 * a separate ``window.location`` read for the first paint.
 */
import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

export type AtriumLocationDetail = {
  pathname: string;
  search: string;
  hash: string;
  /** Monotonic counter, incremented atomically by atrium on every
   *  ``atrium:locationchange`` dispatch. Always present on events
   *  from atrium 0.16+. The value has no semantic meaning — only that
   *  it's strictly greater than the previous event's nonce. Use it in
   *  effect deps when you want to re-run on every navigation event,
   *  including a re-click of the same href that react-router would
   *  otherwise no-op. */
  nonce: number;
};

export const ATRIUM_LOCATION_EVENT = 'atrium:locationchange';

let nextNonce = 0;

/** Fire a single ``atrium:locationchange`` event on ``window``.
 *
 *  Callers pass ``{pathname, search, hash}``; the helper adds a fresh
 *  monotonic nonce. Exported so the few atrium-side call sites that
 *  need to force a dispatch (notification href clicks where the target
 *  matches the current URL — see #81) can do so without depending on
 *  the bridge's effect firing.
 */
export function dispatchLocationChange(
  detail: Omit<AtriumLocationDetail, 'nonce'>,
): void {
  if (typeof window === 'undefined') return;
  const nonce = ++nextNonce;
  window.dispatchEvent(
    new CustomEvent<AtriumLocationDetail>(ATRIUM_LOCATION_EVENT, {
      detail: { ...detail, nonce },
    }),
  );
}

/** Force-fire ``atrium:locationchange`` from a known same-URL navigate.
 *
 *  ``navigate(href)`` in react-router is a no-op when ``href`` matches
 *  the current location, so the bridge's ``useEffect`` doesn't run and
 *  no event is dispatched. Atrium-side handlers that drive deep-link
 *  UI from a notification href need a re-fire even on the same URL —
 *  the user clicking the same bell item twice should still notify the
 *  host's listener (#81). Call this **after** ``navigate(href)`` and
 *  the dispatch reads ``window.location`` directly so the event always
 *  reflects the URL the user is now on. */
export function announceCurrentLocation(): void {
  if (typeof window === 'undefined') return;
  dispatchLocationChange({
    pathname: window.location.pathname,
    search: window.location.search,
    hash: window.location.hash,
  });
}

/** Mounts inside atrium's ``<BrowserRouter>`` and re-dispatches every
 *  react-router location change as a ``window`` CustomEvent so host
 *  bundles can observe in-place navigations (e.g. clicking a
 *  notification whose ``href`` deep-links into the same route the user
 *  is already viewing). Renders nothing.
 *
 *  ``useLocation()`` reflects every commit to atrium's router —
 *  ``navigate(href)``, ``<Link>`` clicks, browser back/forward (the
 *  router translates ``popstate`` into a location change), and the
 *  initial mount. Each commit fires one event. Component is a no-op
 *  outside a Router context, but App.tsx always renders it inside the
 *  BrowserRouter so that's the only branch we exercise. */
export function NavigationBridge(): null {
  const location = useLocation();
  useEffect(() => {
    dispatchLocationChange({
      pathname: location.pathname,
      search: location.search,
      hash: location.hash,
    });
  }, [location.pathname, location.search, location.hash]);
  return null;
}

/** Test-only: reset the module-level nonce counter so each test starts
 *  from a known baseline. Production code never calls this. */
export function __resetNavigationNonceForTests(): void {
  nextNonce = 0;
}
