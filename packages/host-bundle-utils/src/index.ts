// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Atrium host-bundle runtime helpers.
 *
 * Atrium loads each host's frontend as a single ES module via
 * `import(system.host_bundle_url)` after the SPA boots. The host
 * bundle calls `window.__ATRIUM_REGISTRY__.register*(...)` at import
 * time. The elements registered are atrium-React elements (created
 * via `window.React.createElement`) whose ref callback mounts the
 * host's *own* React tree inside via `react-dom/client`'s
 * `createRoot`. Two React trees coexist in the DOM:
 *
 *   - atrium's React owns the page shell + the wrapper `<div>`
 *   - the host's React owns the subtree (Mantine, hook state, query
 *     cache)
 *
 * `makeWrapperElement` and `mountInside` package up the dual-tree
 * pattern so the host's `main.tsx` becomes ten lines of registration
 * calls — see `examples/hello-world/frontend/src/main.tsx` for the
 * canonical use.
 *
 * Type re-exports below let a host that only needs the runtime
 * helpers add a single dep instead of two.
 */
import type { ReactElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';

export { __atrium_t__ } from './i18n';

export type {
  AdminUserRow,
  AdminTab,
  AtriumEvent,
  AtriumEventHandler,
  AtriumNotification,
  AtriumRegistry,
  HomeWidget,
  HomeWidgetWidth,
  LocaleOverlay,
  NavItem,
  NotificationKindRenderer,
  ProfileItem,
  ProfileSlot,
  RouteEntry,
  UserContext,
} from '@brendanbank/atrium-host-types';

interface AtriumReactGlobal {
  createElement: (
    type: string,
    props: Record<string, unknown>,
    ...children: unknown[]
  ) => unknown;
}

/** Resolve the React instance atrium exposes on `window.React`. Throws
 *  with a clear message when missing — the host bundle's import-time
 *  side-effects are running before the SPA mounted, which means the
 *  bundle is being loaded outside atrium's own loader. */
function getAtriumReact(): AtriumReactGlobal {
  if (typeof window === 'undefined') {
    throw new Error(
      '[atrium-host-bundle-utils] makeWrapperElement requires a browser ' +
        'environment; called from a non-window context',
    );
  }
  const r = (window as unknown as { React?: AtriumReactGlobal }).React;
  if (!r || typeof r.createElement !== 'function') {
    throw new Error(
      '[atrium-host-bundle-utils] window.React is missing — atrium SPA ' +
        'must mount and expose its React on window.React before the host ' +
        'bundle is imported. Check that the bundle is being loaded via ' +
        "atrium's host_bundle_url loader and not by the host's own SPA.",
    );
  }
  return r;
}

interface MountState {
  root: Root;
  child: ReactElement;
}

// WeakMap so a DOM element going away (host route swap, profile card
// re-render) doesn't pin the React root in memory. The entry is GC'd
// alongside the element.
const mounted = new WeakMap<HTMLElement, MountState>();

/** Mount `child` inside `el` using a fresh React root, idempotent on
 *  the same `el`/`child` pair.
 *
 *  Behaviour:
 *
 *  - First call: `createRoot(el).render(child)` and remember the root.
 *  - Same `el` + same `child` reference: no-op (handles `<StrictMode>`
 *    double-invoke and ref-callback re-fires on remount).
 *  - Same `el` + different `child` reference: re-renders into the
 *    existing root — cheaper than unmount/remount and preserves
 *    component state where the new child's tree matches.
 *
 *  Hosts use this directly only when they want to manage their own
 *  ref semantics. The common case is `makeWrapperElement(child)`
 *  below, which closes over a single child and tracks the mounted
 *  node via the ref callback's `null` signal so unmount is exact. */
export function mountInside(el: HTMLElement, child: ReactElement): void {
  const existing = mounted.get(el);
  if (existing) {
    if (existing.child === child) return;
    existing.root.render(child);
    existing.child = child;
    return;
  }
  const root = createRoot(el);
  root.render(child);
  mounted.set(el, { root, child });
}

/** Unmount the React root previously attached to `el` by `mountInside`.
 *  No-op when there is no tracked root. Called automatically by the
 *  ref callback returned from `makeWrapperElement`; hosts only call
 *  this directly when managing their own ref semantics. */
export function unmountInside(el: HTMLElement): void {
  const existing = mounted.get(el);
  if (!existing) return;
  existing.root.unmount();
  mounted.delete(el);
}

/** Build an atrium-React element whose ref callback mounts `child` via
 *  the host's own React. Returns a `ReactElement` so it slots
 *  directly into the registry option-bag types (`render: () =>
 *  makeWrapperElement(<MyWidget />)`).
 *
 *  Each call captures the supplied `child` in a closure and tracks the
 *  mounted DOM node so the React unmount fires when atrium drops the
 *  wrapper (route swap, tab change). The closure-style tracking is the
 *  correct fix for issue #31 — using a module-level WeakMap alone
 *  meant a child swap on a reused DOM node could leave the previous
 *  child's tree mounted; pinning state to one closure-per-call
 *  guarantees one wrapper element owns one mount.
 *
 *  Note: the returned object is created via *atrium's* React, not the
 *  host bundle's. The two trees only meet at this `<div>`; everything
 *  inside the ref callback runs under the host's React. The
 *  `ReactElement` cast is safe because atrium's React exposes the
 *  same element shape — the type system can't tell them apart, and
 *  the registry consumer treats either as opaque.
 *
 *  Tabler icons (and other hooks-free SVG components) can be passed
 *  directly to `window.React.createElement(...)` — they don't need
 *  the wrapper. The wrapper is only required for trees that use
 *  hooks, context, or anything that depends on the host's React copy. */
export function makeWrapperElement(child: ReactElement): ReactElement {
  const AtriumReact = getAtriumReact();
  let mountedNode: HTMLElement | null = null;
  let mountedRoot: Root | null = null;

  return AtriumReact.createElement('div', {
    ref: (el: HTMLElement | null) => {
      // React calls the ref with `null` on unmount and again with the
      // node on mount. Same node twice in a row is the StrictMode /
      // remount case — skip.
      if (el === mountedNode) return;
      if (mountedRoot && mountedNode) {
        mountedRoot.unmount();
        mountedRoot = null;
      }
      mountedNode = el;
      if (el) {
        mountedRoot = createRoot(el);
        mountedRoot.render(child);
      }
    },
  }) as ReactElement;
}
