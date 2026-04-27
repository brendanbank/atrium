// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Atrium host-extension registry.
 *
 * Atrium ships only the platform shell. Host applications inject their
 * own UI fragments via five registries — home widgets, routes, nav
 * items, admin tabs, and profile items — populated at SPA boot from a
 * runtime-loaded host bundle (see ``main.tsx`` and
 * ``system.host_bundle_url``).
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

export type HomeWidget = {
  key: string;
  render: () => ReactElement;
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

const homeWidgets: HomeWidget[] = [];
const routes: RouteEntry[] = [];
const navItems: NavItem[] = [];
const adminTabs: AdminTab[] = [];
const profileItems: ProfileItem[] = [];

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

export const __ATRIUM_REGISTRY__ = {
  registerHomeWidget,
  registerRoute,
  registerNavItem,
  registerAdminTab,
  registerProfileItem,
} as const;

export type AtriumRegistry = typeof __ATRIUM_REGISTRY__;

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

/** Test-only: drop every registration. Production code never calls
 *  this — host bundles register once at boot and stay. */
export function __resetRegistryForTests(): void {
  homeWidgets.length = 0;
  routes.length = 0;
  navItems.length = 0;
  adminTabs.length = 0;
  profileItems.length = 0;
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
};
