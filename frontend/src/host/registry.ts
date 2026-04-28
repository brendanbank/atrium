// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Atrium host-extension registry.
 *
 * Atrium ships only the platform shell. Host applications inject their
 * own UI fragments via six registries — home widgets, routes, nav
 * items, admin tabs, profile items, and notification renderers —
 * populated at SPA boot from a runtime-loaded host bundle (see
 * ``main.tsx`` and ``system.host_bundle_url``).
 *
 * The registries are deliberately thin: each one is an array, ordered
 * by registration call order, and the consumer components iterate
 * them at first render. There is no mutation channel after boot —
 * every host bundle's import-time side-effects must complete before
 * React mounts, otherwise the consumer would render before the
 * registration call lands.
 *
 * The same module exposes both:
 *
 *  - typed ``register*`` and ``get*`` functions, used by atrium's own
 *    consumer components and by in-tree tests, and
 *  - a ``window.__ATRIUM_REGISTRY__`` global pointing at the same
 *    underlying state, so the runtime-loaded host bundle can call
 *    ``register*`` without importing this file.
 */
import type { ReactElement } from 'react';

import type { CurrentUser } from '@/lib/auth';
import type { AppNotification } from '@/hooks/useNotifications';

/** Layout width for a home-page widget. ``narrow`` matches the default
 *  680px column atrium ships for the welcome content; ``wide`` extends
 *  out to a comfortable dashboard column; ``full`` lets the widget own
 *  the full panel (still inside ``AppShell.Main``'s padding). Default
 *  is ``narrow`` so existing widgets keep their current layout. */
export type HomeWidgetWidth = 'narrow' | 'wide' | 'full';

export type HomeWidget = {
  key: string;
  render: () => ReactElement;
  width?: HomeWidgetWidth;
};

export type RouteEntry = {
  key: string;
  path: string;
  element: ReactElement;
  /** Default true. Set false for public routes (e.g. host-supplied
   *  unauthenticated landing pages). */
  requireAuth?: boolean;
  /** Default 'shell'. Wraps the route in atrium's AppLayout (header +
   *  sidebar). 'bare' renders the element with no chrome. */
  layout?: 'shell' | 'bare';
};

export type NavItem = {
  key: string;
  label: string;
  to: string;
  icon?: ReactElement;
  /** Optional visibility predicate. Default: always visible. The
   *  predicate is called with the current ``me`` context (or null when
   *  the SPA hasn't resolved auth yet). */
  condition?: (ctx: { me: CurrentUser | null }) => boolean;
};

export type AdminTab = {
  key: string;
  label: string;
  icon?: ReactElement;
  /** Permission code; the tab is hidden for users who don't hold it.
   *  Omit to show the tab to every admin viewer. */
  perm?: string;
  element: ReactElement;
};

/** Slot inside ``ProfilePage``'s vertical card stack where a host
 *  item is inserted. Default ``after-roles`` — the natural place for
 *  extra preferences. */
export type ProfileSlot =
  | 'after-profile'
  | 'after-password'
  | 'after-2fa'
  | 'after-roles'
  | 'after-sessions'
  | 'before-delete';

export type ProfileItem = {
  key: string;
  /** Insertion slot. Default ``after-roles``. */
  slot?: ProfileSlot;
  /** Optional visibility predicate, mirrors ``NavItem``. The profile
   *  page early-returns on a missing user, so ``me`` is never null
   *  when this fires. */
  condition?: (ctx: { me: CurrentUser }) => boolean;
  render: () => ReactElement;
};

/** Per-kind renderer for a notification row. Atrium emits
 *  ``{kind, payload}`` rows but ships no built-in formatting — each
 *  host app registers a renderer for the kinds it cares about. The
 *  bell + inbox fall back to ``kind`` + raw-JSON payload for any kind
 *  with no registered renderer.
 *
 *  Atrium calls the helpers in three places:
 *
 *  - bell list line / inbox row body → ``title(n)`` if provided,
 *    otherwise ``n.kind``. ``render`` is *not* invoked per row;
 *    list rendering is intentionally a string lookup so a long inbox
 *    isn't a per-row React tree.
 *  - row click / "View" → ``href(n)`` if provided is passed to
 *    react-router ``navigate``; otherwise atrium opens the detail
 *    modal.
 *  - detail modal body → ``render(n)`` element if provided,
 *    otherwise the fallback ``<pre>`` of ``JSON.stringify(payload)``.
 *
 *  The ``render`` element follows the same wrapper-element contract
 *  as ``HomeWidget.render`` / ``RouteEntry.element``: it's an
 *  atrium-React element, typically a ``<div>`` whose ``ref`` mounts
 *  the host's React tree inside.
 */
export type NotificationKindRenderer = {
  /** Notification ``kind`` string this renderer handles. Match is
   *  exact; no glob / prefix matching. Duplicate registrations for
   *  the same kind warn and last-write-wins. */
  kind: string;
  /** Detail-modal body. Receives the full notification row. */
  render: (n: AppNotification) => ReactElement;
  /** Compact summary for the bell + inbox row (and the modal title).
   *  Plain string so the list iterates cheaply. */
  title?: (n: AppNotification) => string;
  /** App-internal href for the row click. Passed to react-router
   *  ``navigate`` — keep it relative to the SPA root (e.g.
   *  ``/calendar?focus=block:1``). When set, the row click navigates
   *  instead of opening the detail modal. */
  href?: (n: AppNotification) => string;
};

const homeWidgets: HomeWidget[] = [];
const routes: RouteEntry[] = [];
const navItems: NavItem[] = [];
const adminTabs: AdminTab[] = [];
const profileItems: ProfileItem[] = [];
const notificationRenderers: NotificationKindRenderer[] = [];

function registerHomeWidget(widget: HomeWidget): void {
  if (homeWidgets.some((w) => w.key === widget.key)) {
    console.warn(
      `[atrium-registry] duplicate home widget key "${widget.key}"; ` +
        `last registration wins`,
    );
    const idx = homeWidgets.findIndex((w) => w.key === widget.key);
    homeWidgets.splice(idx, 1);
  }
  homeWidgets.push(widget);
}

function registerRoute(route: RouteEntry): void {
  // Path collisions are last-write-wins so a host can deliberately
  // override an atrium route, but we surface a console warning so the
  // collision is visible during integration.
  const collide = routes.find((r) => r.path === route.path);
  if (collide) {
    console.warn(
      `[atrium-registry] route path "${route.path}" already registered ` +
        `(key "${collide.key}"); replacing with "${route.key}"`,
    );
    const idx = routes.indexOf(collide);
    routes.splice(idx, 1);
  }
  if (routes.some((r) => r.key === route.key)) {
    const idx = routes.findIndex((r) => r.key === route.key);
    routes.splice(idx, 1);
  }
  routes.push(route);
}

function registerNavItem(item: NavItem): void {
  if (navItems.some((n) => n.key === item.key)) {
    const idx = navItems.findIndex((n) => n.key === item.key);
    navItems.splice(idx, 1);
  }
  navItems.push(item);
}

function registerAdminTab(tab: AdminTab): void {
  if (adminTabs.some((t) => t.key === tab.key)) {
    const idx = adminTabs.findIndex((t) => t.key === tab.key);
    adminTabs.splice(idx, 1);
  }
  adminTabs.push(tab);
}

function registerProfileItem(item: ProfileItem): void {
  if (profileItems.some((p) => p.key === item.key)) {
    console.warn(
      `[atrium-registry] duplicate profile item key "${item.key}"; ` +
        `last registration wins`,
    );
    const idx = profileItems.findIndex((p) => p.key === item.key);
    profileItems.splice(idx, 1);
  }
  profileItems.push(item);
}

function registerNotificationKind(renderer: NotificationKindRenderer): void {
  if (notificationRenderers.some((r) => r.kind === renderer.kind)) {
    console.warn(
      `[atrium-registry] duplicate notification renderer kind "${renderer.kind}"; ` +
        `last registration wins`,
    );
    const idx = notificationRenderers.findIndex(
      (r) => r.kind === renderer.kind,
    );
    notificationRenderers.splice(idx, 1);
  }
  notificationRenderers.push(renderer);
}

const baseRegistry = {
  registerHomeWidget,
  registerRoute,
  registerNavItem,
  registerAdminTab,
  registerProfileItem,
  registerNotificationKind,
} as const;

export type AtriumRegistry = typeof baseRegistry;

/** Wrap the registry in a Proxy so a host bundle that targets a newer
 *  atrium build (e.g. it calls ``registerSettingsTab`` against an
 *  image that hasn't shipped that slot yet) gets a clear console
 *  warning instead of a ``TypeError: ... is not a function`` that
 *  unwinds mid-bundle and loses every prior registration. The typed
 *  exports above stay the source of truth for what should exist; the
 *  Proxy is purely a runtime safety net. */
const registryProxy = new Proxy(baseRegistry, {
  get(target, prop, receiver) {
    if (typeof prop === 'symbol' || prop in target) {
      return Reflect.get(target, prop, receiver);
    }
    const propStr = String(prop);
    return (...args: unknown[]): void => {
      const arg = args[0] as { key?: unknown } | undefined;
      const key = typeof arg?.key === 'string' ? arg.key : '<unknown>';
      console.warn(
        `[atrium-registry] host bundle called __ATRIUM_REGISTRY__.${propStr}(...) ` +
          `but that method is not available in this atrium build ` +
          `(key="${key}"). Registration ignored — upgrade the atrium ` +
          `image or remove the call from the host bundle.`,
      );
    };
  },
}) as AtriumRegistry;

export const __ATRIUM_REGISTRY__: AtriumRegistry = registryProxy;

export function getHomeWidgets(): readonly HomeWidget[] {
  return homeWidgets;
}

export function getRoutes(): readonly RouteEntry[] {
  return routes;
}

export function getNavItems(): readonly NavItem[] {
  return navItems;
}

export function getAdminTabs(): readonly AdminTab[] {
  return adminTabs;
}

export function getProfileItems(): readonly ProfileItem[] {
  return profileItems;
}

export function getNotificationRenderers(): readonly NotificationKindRenderer[] {
  return notificationRenderers;
}

/** Look up the renderer for a single notification kind. Returns
 *  ``undefined`` when no host has registered for it; callers fall
 *  back to atrium's generic kind+JSON rendering. */
export function lookupNotificationRenderer(
  kind: string,
): NotificationKindRenderer | undefined {
  return notificationRenderers.find((r) => r.kind === kind);
}

/** Test-only: drop every registration. Production code never calls
 *  this — host bundles register once at boot and stay. */
export function __resetRegistryForTests(): void {
  homeWidgets.length = 0;
  routes.length = 0;
  navItems.length = 0;
  adminTabs.length = 0;
  profileItems.length = 0;
  notificationRenderers.length = 0;
}

declare global {
  interface Window {
    __ATRIUM_REGISTRY__?: AtriumRegistry;
  }
}

if (typeof window !== 'undefined') {
  window.__ATRIUM_REGISTRY__ = __ATRIUM_REGISTRY__;
}

export {
  registerHomeWidget,
  registerRoute,
  registerNavItem,
  registerAdminTab,
  registerProfileItem,
  registerNotificationKind,
};
