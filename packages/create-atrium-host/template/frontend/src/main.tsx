/** Host bundle entry.
 *
 * Atrium loads this module via `import(system.host_bundle_url)` after
 * the SPA boots. The import-time side-effects below populate the
 * registry. The dual-tree mount pattern (atrium-React owns the
 * wrapper, the host's React owns the subtree) is encapsulated in
 * `makeWrapperElement` from `@brendanbank/atrium-host-bundle-utils`.
 */
import { IconHandStop } from '@tabler/icons-react';
import {
  type AtriumRegistry,
  makeWrapperElement,
} from '@brendanbank/atrium-host-bundle-utils';

import { __BRAND_PASCAL__AdminTab } from './__BRAND_PASCAL__AdminTab';
import { __BRAND_PASCAL__Page } from './__BRAND_PASCAL__Page';
import { __BRAND_PASCAL__ProfileItem } from './__BRAND_PASCAL__ProfileItem';
import { __BRAND_PASCAL__Widget } from './__BRAND_PASCAL__Widget';

const reg = window.__ATRIUM_REGISTRY__ as AtriumRegistry | undefined;
const AtriumReact = window.React;

if (!reg || !AtriumReact) {
  console.error(
    '[__HOST_NAME__] window.__ATRIUM_REGISTRY__ or window.React missing — atrium SPA must mount before the host bundle loads',
  );
} else {
  reg.registerHomeWidget({
    key: '__HOST_NAME__-widget',
    render: () => makeWrapperElement(<__BRAND_PASCAL__Widget />),
  });
  reg.registerRoute({
    key: '__HOST_NAME__-page',
    path: '/__HOST_NAME__',
    render: () => makeWrapperElement(<__BRAND_PASCAL__Page />),
  });
  reg.registerNavItem({
    key: '__HOST_NAME__-nav',
    label: '__BRAND_NAME__',
    to: '/__HOST_NAME__',
    icon: AtriumReact.createElement(IconHandStop, { size: 18 }),
  });
  reg.registerAdminTab({
    key: '__HOST_NAME__',
    label: '__BRAND_NAME__',
    icon: AtriumReact.createElement(IconHandStop, { size: 14 }),
    perm: '__HOST_PKG__.write',
    render: () => makeWrapperElement(<__BRAND_PASCAL__AdminTab />),
  });
  reg.registerProfileItem({
    key: '__HOST_NAME__-profile',
    slot: 'after-roles',
    render: () => makeWrapperElement(<__BRAND_PASCAL__ProfileItem />),
  });
}
