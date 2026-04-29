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
 * To close the gap atrium dispatches a single ``atrium:locationchange``
 * CustomEvent on ``window`` whenever its router commits a new location.
 * The detail payload mirrors ``window.location``: ``{pathname, search,
 * hash}``. Hosts subscribe with a plain ``addEventListener`` (no React
 * coupling) or via the ``useAtriumLocation()`` hook in
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
};

export const ATRIUM_LOCATION_EVENT = 'atrium:locationchange';

/** Fire a single ``atrium:locationchange`` event on ``window``. Exported
 *  for tests and for the rare host that wants to replay a synthesised
 *  location to its own subscribers; production code only sees the
 *  events fired by ``NavigationBridge`` below. */
export function dispatchLocationChange(detail: AtriumLocationDetail): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(
    new CustomEvent<AtriumLocationDetail>(ATRIUM_LOCATION_EVENT, { detail }),
  );
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
