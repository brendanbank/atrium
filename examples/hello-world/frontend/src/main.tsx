// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/** Hello World host bundle entry.
 *
 * Atrium loads this module via `import(system.host_bundle_url)` after
 * the SPA boots; the import-time side-effects below populate the
 * registry. The dual-tree mount pattern (atrium-React owns the
 * wrapper, the host's React owns the subtree) is encapsulated in
 * `makeWrapperElement` from `@brendanbank/atrium-host-bundle-utils` — see that
 * package's README for the rationale. The atrium-React reference
 * (`window.React`, exposed by atrium for host bundles) is used only
 * for hooks-free SVG icons that don't need the wrapper trick.
 */
import { IconHandStop } from '@tabler/icons-react';

import {
  type AtriumRegistry,
  makeWrapperElement,
} from '@brendanbank/atrium-host-bundle-utils';

import { HelloAdminTab } from './HelloAdminTab';
import { HelloPage } from './HelloPage';
import { HelloProfileItem } from './HelloProfileItem';
import { HelloWidget } from './HelloWidget';
import {
  HelloToggledNotification,
  helloToggledTitle,
} from './HelloNotification';
import { queryClient } from './queryClient';

const reg = window.__ATRIUM_REGISTRY__ as AtriumRegistry | undefined;
const AtriumReact = window.React;

if (!reg || !AtriumReact) {
  console.error(
    '[atrium-hello-world] window.__ATRIUM_REGISTRY__ or window.React missing — atrium SPA must mount before the host bundle loads',
  );
} else {
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
  // moment another tab (or another user) flips the toggle. The
  // QueryClient here is the host bundle's own — atrium's bell uses
  // its own client and refetches independently.
  reg.subscribeEvent('hello.toggled', () => {
    queryClient.invalidateQueries({ queryKey: ['hello', 'state'] });
  });
}
