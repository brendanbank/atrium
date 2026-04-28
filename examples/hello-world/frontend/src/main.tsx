// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/** Hello World host bundle entry.
 *
 * Bundles its own React + ReactDOM + Mantine + TanStack Query. The
 * registered elements are atrium-React elements (created via
 * ``window.React.createElement``) that own a single ``<div>`` wrapper
 * each; the div's ref callback mounts our React tree inside via our
 * bundled ``createRoot``. Two React trees coexist in the DOM:
 *
 *   - atrium's React owns the shell + the wrapper element + routing
 *   - our React owns the subtree (Mantine widgets, hook state, query
 *     cache)
 *
 * Hooks never cross the boundary — atrium's reconciler only ever
 * calls our ``ref`` callback, never our component functions.
 */
import { createRoot, type Root } from 'react-dom/client';
import { IconHandStop } from '@tabler/icons-react';

import { HelloAdminTab } from './HelloAdminTab';
import { HelloPage } from './HelloPage';
import { HelloProfileItem } from './HelloProfileItem';
import { HelloWidget } from './HelloWidget';
import {
  HelloToggledNotification,
  helloToggledTitle,
} from './HelloNotification';
import { queryClient } from './queryClient';

interface HostNotification {
  id: number;
  kind: string;
  payload: Record<string, unknown>;
  read_at: string | null;
  created_at: string;
}

interface AtriumEvent {
  kind: string;
  payload: Record<string, unknown>;
}

interface AtriumRegistry {
  registerHomeWidget: (w: { key: string; render: () => unknown }) => void;
  registerRoute: (r: {
    key: string;
    path: string;
    render: () => unknown;
    requireAuth?: boolean;
    layout?: 'shell' | 'bare';
  }) => void;
  registerNavItem: (n: {
    key: string;
    label: string;
    to: string;
    icon?: unknown;
  }) => void;
  registerAdminTab: (t: {
    key: string;
    label: string;
    icon?: unknown;
    perm?: string;
    render: () => unknown;
  }) => void;
  registerProfileItem: (p: {
    key: string;
    slot?:
      | 'after-profile'
      | 'after-password'
      | 'after-2fa'
      | 'after-roles'
      | 'after-sessions'
      | 'before-delete';
    render: () => unknown;
  }) => void;
  registerNotificationKind: (r: {
    kind: string;
    render: (n: HostNotification) => unknown;
    title?: (n: HostNotification) => string;
    href?: (n: HostNotification) => string;
  }) => void;
  registerLocale: (o: {
    locale: string;
    strings: Record<string, unknown>;
  }) => void;
  subscribeEvent: (
    kind: string,
    handler: (event: AtriumEvent) => void,
  ) => () => void;
}

/** atrium's React, exposed at ``window.React`` by atrium's main.tsx
 *  so host bundles can create elements that atrium's reconciler will
 *  render. Our wrapper elements use this; everything inside the
 *  wrappers uses our bundled React. */
const AtriumReact = (
  window as unknown as { React?: { createElement: (...a: unknown[]) => unknown } }
).React;

if (!AtriumReact) {
  console.error(
    '[atrium-hello-world] window.React missing — atrium SPA must mount before the host bundle loads',
  );
}

/** Track per-element roots so we don't double-mount when atrium
 *  re-runs the ref callback (StrictMode, route remounts). */
type MountedEl = HTMLElement & { __helloRoot?: Root };

function mountInside(el: HTMLElement | null, child: React.ReactElement): void {
  if (!el) return;
  const slot = el as MountedEl;
  if (slot.__helloRoot) return;
  slot.__helloRoot = createRoot(slot);
  slot.__helloRoot.render(child);
}

function makeWrapperElement(child: React.ReactElement): unknown {
  return AtriumReact!.createElement('div', {
    // The ref runs after atrium's React commits the wrapper div to
    // the DOM; we then create our own React root inside it.
    ref: (el: HTMLElement | null) => mountInside(el, child),
  });
}

const reg = (window as unknown as { __ATRIUM_REGISTRY__?: AtriumRegistry })
  .__ATRIUM_REGISTRY__;

if (!reg) {
  console.error(
    '[atrium-hello-world] window.__ATRIUM_REGISTRY__ missing — atrium SPA must mount before the host bundle loads',
  );
} else if (AtriumReact) {
  reg.registerHomeWidget({
    key: 'hello-world',
    render: () => makeWrapperElement(<HelloWidget />),
  });
  reg.registerRoute({
    key: 'hello-page',
    path: '/hello',
    render: () => makeWrapperElement(<HelloPage />),
  });
  reg.registerNavItem({
    key: 'hello-nav',
    label: 'Hello World',
    to: '/hello',
    // The icon is rendered by atrium's React (it's part of atrium's
    // sidebar), so we create it via atrium's React too.
    icon: AtriumReact.createElement(IconHandStop, { size: 18 }),
  });
  reg.registerAdminTab({
    key: 'hello',
    label: 'Hello World',
    icon: AtriumReact.createElement(IconHandStop, { size: 14 }),
    perm: 'hello.toggle',
    render: () => makeWrapperElement(<HelloAdminTab />),
  });
  reg.registerProfileItem({
    key: 'hello-profile',
    slot: 'after-roles',
    render: () => makeWrapperElement(<HelloProfileItem />),
  });
  reg.registerNotificationKind({
    kind: 'hello.toggled',
    title: helloToggledTitle,
    render: (n) =>
      makeWrapperElement(
        <HelloToggledNotification
          payload={n.payload}
          createdAt={n.created_at}
        />,
      ),
  });
  // Subscribe to the typed SSE event so the widget refreshes the
  // moment another tab (or another user) flips the toggle, instead
  // of waiting for the 5s polling interval. The QueryClient here is
  // the host bundle's own — atrium's bell uses its own client and
  // refetches independently. See ``queryClient.ts``: ``refetchInterval``
  // is now off, the SSE stream owns freshness.
  reg.subscribeEvent('hello.toggled', () => {
    queryClient.invalidateQueries({ queryKey: ['hello', 'state'] });
  });
}
