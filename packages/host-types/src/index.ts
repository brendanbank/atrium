// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Source-of-truth TypeScript declarations for the atrium host-extension
 * contract. A host bundle imports these types so its registration calls
 * are checked against the same shapes atrium's own consumer components
 * read.
 *
 * The package version tracks atrium's image version (`^0.14` of this
 * package implies "compatible with atrium 0.14.x"). New registry slots
 * land here when they ship in atrium; bumping the package picks them
 * up. A host that calls a method missing on the pinned major gets a
 * TypeScript error before runtime — the runtime Proxy on
 * `window.__ATRIUM_REGISTRY__` is a belt-and-braces fallback for
 * version skew, not a substitute for typing.
 */

import type { ReactElement } from 'react';

// ---------------------------------------------------------------------------
// Identity / context
// ---------------------------------------------------------------------------

/** Shape of `GET /users/me/context` — the atrium-owned RBAC view of the
 *  signed-in user. The bundled hook in `@brendanbank/atrium-host-bundle-utils/react`
 *  returns this exact shape. */
export interface UserContext {
  id: number;
  email: string;
  full_name: string;
  is_active: boolean;
  roles: string[];
  permissions: string[];
  impersonating_from: { id: number; email: string; full_name: string } | null;
}

/** Shape of `GET /admin/users` rows (and `/admin/users/{id}` responses).
 *  Hosts that render their own admin UIs against atrium's user list
 *  read this shape. The patch endpoint accepts `role_ids`; the read
 *  shape carries both `role_ids` and the human-readable `roles` codes. */
export interface AdminUserRow {
  id: number;
  email: string;
  is_active: boolean;
  is_verified: boolean;
  full_name: string;
  phone: string | null;
  preferred_language: 'en' | 'nl';
  role_ids: number[];
  roles: string[];
}

// ---------------------------------------------------------------------------
// Window event payloads
// ---------------------------------------------------------------------------

/** Detail payload of the ``atrium:userchange`` window CustomEvent
 *  atrium dispatches whenever the signed-in user identity changes —
 *  login, logout, logout-all, impersonation start/stop, same-tab
 *  re-login as a different user. ``previous`` and ``current`` are user
 *  ids; ``null`` means signed out (or, for ``previous``, transitioning
 *  out of the signed-out state). ``nonce`` is a monotonic per-event
 *  counter. The event does NOT fire on first identity observation
 *  after a page load (the user has not changed).
 *
 *  Available since atrium 0.18. The canonical use is host bundles
 *  clearing their own QueryClient cache when the user changes — atrium
 *  clears its own cache via ``qc.clear()`` on logout, but a host bundle
 *  runs a separate QueryClient (by design — see
 *  ``@brendanbank/atrium-host-bundle-utils/react``) and needs an
 *  external signal:
 *
 *  ```ts
 *  window.addEventListener('atrium:userchange', () => {
 *    hostQueryClient.clear();
 *  });
 *  ```
 */
export interface AtriumUserChangeDetail {
  previous: number | null;
  current: number | null;
  nonce: number;
}

// ---------------------------------------------------------------------------
// Notification + event payloads
// ---------------------------------------------------------------------------

/** A single notification row as the SPA sees it. `kind` is host-defined;
 *  `payload` is opaque JSON. `read_at` is null until the user clears the
 *  bell; `created_at` is the server-side timestamp. */
export interface AtriumNotification {
  id: number;
  kind: string;
  payload: Record<string, unknown>;
  read_at: string | null;
  created_at: string;
}

/** SSE `notification` event published by `app.services.notifications.notify_user`.
 *  Same wire shape as the row's body — `kind` matches what
 *  `registerNotificationKind` listens on. */
export interface AtriumEvent {
  kind: string;
  payload: Record<string, unknown>;
}

export type AtriumEventHandler = (event: AtriumEvent) => void;

// ---------------------------------------------------------------------------
// Registry slot shapes
// ---------------------------------------------------------------------------

/** Layout width for a home-page widget. `narrow` matches atrium's default
 *  680px column; `wide` extends to a comfortable dashboard column; `full`
 *  takes the whole panel inside `AppShell.Main`. Default `narrow`. */
export type HomeWidgetWidth = 'narrow' | 'wide' | 'full';

export interface HomeWidget {
  key: string;
  render: () => ReactElement;
  width?: HomeWidgetWidth;
}

export interface RouteEntry {
  key: string;
  path: string;
  /** Returns a fresh element each time the route mounts. Strongly
   *  preferred — see the host-bundle wrapper-element rationale in
   *  `docs/published-images.md`. Exactly one of `render` / `element`
   *  must be supplied. */
  render?: () => ReactElement;
  /** @deprecated Pass `render: () => element` instead. Captured
   *  elements share the same DOM node across navigations and can carry
   *  stale state. Kept for back-compat with hosts built against
   *  pre-0.12 atrium. */
  element?: ReactElement;
  /** Default `true`. Set false for public routes (e.g. host landing pages). */
  requireAuth?: boolean;
  /** Default `'shell'`. `'bare'` skips atrium's AppLayout wrapper. */
  layout?: 'shell' | 'bare';
}

export interface NavItem {
  key: string;
  label: string;
  to: string;
  icon?: ReactElement;
  /** Optional visibility predicate. Default: always visible. `me` is
   *  null until the SPA's auth probe resolves. */
  condition?: (ctx: { me: UserContext | null }) => boolean;
  /** Optional sort key. Lower values render higher in the sidebar.
   *  Items without `order` keep insertion order, sorted **after** every
   *  item that has one. Atrium's built-in nav items use 100/200/300
   *  (Home, Notifications, Admin) so a host can pick a number to
   *  interleave with them — e.g. `order: 250` to land between
   *  Notifications and Admin. Available since atrium 0.16. */
  order?: number;
}

/** Sidebar bucket an admin tab lives in. `admin` is the default and
 *  groups every atrium-shipped admin surface plus host admin tooling.
 *  `settings` is a parallel sibling group above Admin reserved for
 *  application-level preferences — atrium ships zero items here, so
 *  the Settings parent hides entirely until a host registers into it.
 *  Available since atrium 0.17. */
export type AdminSection = 'admin' | 'settings';

export interface AdminTab {
  key: string;
  label: string;
  icon?: ReactElement;
  /** Permission code; the tab is hidden for users without it. Omit to
   *  show the tab to every viewer with admin access. */
  perm?: string;
  /** Sidebar bucket. Default `'admin'`. Set `'settings'` to push a
   *  host-app preference page into the Settings group instead.
   *  Available since atrium 0.17. */
  section?: AdminSection;
  /** Returns a fresh element each time the tab is selected. Strongly
   *  preferred — see `RouteEntry.render`. Exactly one of `render` /
   *  `element` must be supplied. */
  render?: () => ReactElement;
  /** @deprecated Pass `render: () => element` instead. */
  element?: ReactElement;
  /** Optional sort key. Lower values render higher in the sidebar
   *  group. Items without `order` keep registration order, sorted
   *  **after** every item that has one. Atrium's built-in admin tabs
   *  use 100..900 in steps of 100; a host tab with `order: 750`
   *  would slot between Email templates (700) and Reminders (800).
   *  Available since atrium 0.16. */
  order?: number;
}

/** Insertion slot inside `ProfilePage`'s vertical card stack. Default
 *  `'after-roles'` — the natural place for extra preferences. */
export type ProfileSlot =
  | 'after-profile'
  | 'after-password'
  | 'after-2fa'
  | 'after-roles'
  | 'after-sessions'
  | 'before-delete';

export interface ProfileItem {
  key: string;
  /** Insertion slot. Default `'after-roles'`. */
  slot?: ProfileSlot;
  /** Optional visibility predicate. The profile page early-returns on a
   *  missing user, so `me` is never null when this fires. */
  condition?: (ctx: { me: UserContext }) => boolean;
  render: () => ReactElement;
  /** Optional sort key within the chosen slot. Lower values render
   *  earlier; items without `order` keep registration order and land
   *  after items that have one. Slots are independent — the sort runs
   *  per-slot. Available since atrium 0.16. */
  order?: number;
}

/** Per-kind renderer for a notification row. Atrium emits `{kind,
 *  payload}` rows but ships no built-in formatting — host apps register
 *  one renderer per kind they care about. */
export interface NotificationKindRenderer {
  /** Notification `kind` string this renderer handles. Match is exact;
   *  no glob / prefix matching. Duplicate registrations for the same
   *  kind warn and last-write-wins. */
  kind: string;
  /** Detail-modal body. Receives the full row. */
  render: (n: AtriumNotification) => ReactElement;
  /** Compact summary for the bell + inbox row line and the modal title. */
  title?: (n: AtriumNotification) => string;
  /** App-internal href. When set, the row click navigates instead of
   *  opening the detail modal. */
  href?: (n: AtriumNotification) => string;
}

/** Locale overlay registered by a host. `strings` is a flat
 *  i18next-style bundle (dot-paths or nested object — both accepted).
 *  Layered on top of atrium's shipped locale + admin overrides;
 *  precedence is shipped < admin overrides < host overlay. */
export interface LocaleOverlay {
  locale: string;
  strings: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Registry surface
// ---------------------------------------------------------------------------

/** The runtime-discovered registry exposed at `window.__ATRIUM_REGISTRY__`.
 *
 *  Optional methods are slots that landed in a later atrium release
 *  than the one that introduced this type — type-narrow before calling
 *  if you intend to support older images, or use the runtime
 *  `__ATRIUM_VERSION__` global for explicit gating. The Proxy on the
 *  registry already turns calls to missing methods into a console
 *  warning + no-op; this is for clean TypeScript checking on top of
 *  that runtime safety net.
 *
 *  When atrium adds a new slot, this type bumps and the slot becomes
 *  optional first; once a release window has passed and `^0.X` no
 *  longer covers the pre-slot images, the slot becomes required. */
export interface AtriumRegistry {
  registerHomeWidget: (widget: HomeWidget) => void;
  registerRoute: (route: RouteEntry) => void;
  registerNavItem: (item: NavItem) => void;
  registerAdminTab: (tab: AdminTab) => void;
  /** Relocate one of atrium's built-in admin tabs into a different
   *  sidebar group, and optionally re-rank it within that group. Pass
   *  the tab's stable atrium key (e.g. `'branding'`, `'emails'`,
   *  `'outbox'`, `'reminders'`, `'translations'`); the perm gate the
   *  built-in already declares is preserved. Available since atrium
   *  0.17. */
  setBuiltinAdminTabSection?: (
    key: string,
    section: AdminSection,
    order?: number,
  ) => void;
  registerProfileItem: (item: ProfileItem) => void;
  registerNotificationKind: (renderer: NotificationKindRenderer) => void;
  registerLocale: (overlay: LocaleOverlay) => void;
  subscribeEvent: (kind: string, handler: AtriumEventHandler) => () => void;
}

// ---------------------------------------------------------------------------
// Window globals atrium exposes for host bundles
// ---------------------------------------------------------------------------

declare global {
  interface Window {
    /** atrium's React instance. Host bundles read this so their
     *  wrapper elements can call `React.createElement(...)` without
     *  bundling a second React copy that atrium's reconciler would
     *  refuse to render. Available since the host-bundle pattern
     *  shipped (atrium 0.10+). */
    React?: typeof import('react');
    /** Backend version string (e.g. "0.14.0") mirrored from
     *  `GET /app-config` before the host bundle is imported, so
     *  import-time code can branch on it. Available since atrium
     *  0.14.0; treat as best-effort on older images. */
    __ATRIUM_VERSION__?: string;
    /** The registry. Populated by atrium before the host bundle
     *  imports; host bundles read it and call its `register*` methods
     *  at module init. */
    __ATRIUM_REGISTRY__?: AtriumRegistry;
  }
}

export {};
