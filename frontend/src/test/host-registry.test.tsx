// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Vitest coverage for the four host extension registries.
 *
 * The registries are module-level state, so each test resets via the
 * exposed ``__resetRegistryForTests`` to avoid bleed between cases.
 *
 * Behaviour pinned down here:
 *  - register* push entries that get* return in registration order.
 *  - duplicate ``key`` for the same registry replaces the prior entry
 *    rather than double-counting.
 *  - ``registerRoute`` warns on path collisions (last-write-wins).
 *  - the global ``window.__ATRIUM_REGISTRY__`` is bound to the same
 *    underlying state as the typed ``register*`` exports — host
 *    bundles loaded at runtime use the global, in-tree code uses the
 *    typed exports, both populate the same arrays.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import {
  __ATRIUM_REGISTRY__,
  __resetRegistryForTests,
  getAdminTabs,
  getHomeWidgets,
  getNavItems,
  getProfileItems,
  getRoutes,
  registerAdminTab,
  registerHomeWidget,
  registerNavItem,
  registerProfileItem,
  registerRoute,
} from '@/host/registry';

describe('host registry', () => {
  beforeEach(() => {
    __resetRegistryForTests();
  });

  it('registerHomeWidget appends entries that getHomeWidgets returns', () => {
    registerHomeWidget({ key: 'a', render: () => <span>A</span> });
    registerHomeWidget({ key: 'b', render: () => <span>B</span> });
    const widgets = getHomeWidgets();
    expect(widgets.map((w) => w.key)).toEqual(['a', 'b']);
  });

  it('registerHomeWidget replaces on duplicate key', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      registerHomeWidget({ key: 'a', render: () => <span>first</span> });
      registerHomeWidget({ key: 'a', render: () => <span>second</span> });
      const widgets = getHomeWidgets();
      expect(widgets).toHaveLength(1);
      expect(warn).toHaveBeenCalledOnce();
    } finally {
      warn.mockRestore();
    }
  });

  it('registerRoute warns on path collision and replaces', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      registerRoute({
        key: 'first',
        path: '/x',
        element: <span>first</span>,
      });
      registerRoute({
        key: 'second',
        path: '/x',
        element: <span>second</span>,
      });
      const routes = getRoutes();
      expect(routes).toHaveLength(1);
      expect(routes[0]?.key).toBe('second');
      expect(warn).toHaveBeenCalledOnce();
    } finally {
      warn.mockRestore();
    }
  });

  it('registerNavItem records condition predicates', () => {
    const condition = vi.fn(() => true);
    registerNavItem({ key: 'n', label: 'Nav', to: '/n', condition });
    const items = getNavItems();
    expect(items).toHaveLength(1);
    expect(items[0]?.condition?.({ me: null })).toBe(true);
    expect(condition).toHaveBeenCalled();
  });

  it('registerAdminTab carries perm code through', () => {
    registerAdminTab({
      key: 't',
      label: 'Tab',
      perm: 'thing.manage',
      element: <span>tab</span>,
    });
    const tabs = getAdminTabs();
    expect(tabs[0]?.perm).toBe('thing.manage');
  });

  it('registerProfileItem appends in registration order', () => {
    registerProfileItem({
      key: 'a',
      slot: 'after-roles',
      render: () => <span>A</span>,
    });
    registerProfileItem({
      key: 'b',
      slot: 'before-delete',
      render: () => <span>B</span>,
    });
    const items = getProfileItems();
    expect(items.map((i) => i.key)).toEqual(['a', 'b']);
    expect(items[0]?.slot).toBe('after-roles');
    expect(items[1]?.slot).toBe('before-delete');
  });

  it('registerProfileItem replaces on duplicate key with a warning', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      registerProfileItem({ key: 'p', render: () => <span>first</span> });
      registerProfileItem({ key: 'p', render: () => <span>second</span> });
      const items = getProfileItems();
      expect(items).toHaveLength(1);
      expect(warn).toHaveBeenCalledOnce();
    } finally {
      warn.mockRestore();
    }
  });

  it('window.__ATRIUM_REGISTRY__ writes through to the same state', () => {
    // The runtime-loaded host bundle calls window.__ATRIUM_REGISTRY__
    // rather than importing the typed exports — this test pins down
    // that the two surfaces share state.
    window.__ATRIUM_REGISTRY__?.registerHomeWidget({
      key: 'global',
      render: () => <span>global</span>,
    });
    const widgets = getHomeWidgets();
    expect(widgets.map((w) => w.key)).toContain('global');
    expect(__ATRIUM_REGISTRY__).toBe(window.__ATRIUM_REGISTRY__);
  });

  afterEach(() => {
    __resetRegistryForTests();
  });
});
