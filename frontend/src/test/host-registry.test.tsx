// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Vitest coverage for the host extension registries.
 *
 * The registries are module-level state, so each test resets via the
 * exposed ``__resetRegistryForTests`` to avoid bleed between cases.
 *
 * Behaviour pinned down here:
 *  - register* push entries that get* return in registration order.
 *  - duplicate ``key`` (or ``kind`` for notifications) replaces the
 *    prior entry rather than double-counting.
 *  - ``registerRoute`` warns on path collisions (last-write-wins).
 *  - ``lookupNotificationRenderer`` returns the registered entry for
 *    a kind, ``undefined`` otherwise.
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
  getLocaleOverlays,
  getNavItems,
  getNotificationRenderers,
  getProfileItems,
  getRoutes,
  lookupNotificationRenderer,
  registerAdminTab,
  registerHomeWidget,
  registerLocale,
  registerNavItem,
  registerNotificationKind,
  registerProfileItem,
  registerRoute,
  subscribeEvent,
  subscribeLocaleOverlay,
} from '@/host/registry';
import {
  __eventBusSubscriberCountForTests,
  dispatchAtriumEvent,
} from '@/host/events';
import type { AppNotification } from '@/hooks/useNotifications';

const sampleNotification = (
  overrides: Partial<AppNotification> = {},
): AppNotification => ({
  id: 1,
  kind: 'sample.kind',
  payload: {},
  read_at: null,
  created_at: '2026-01-01T00:00:00Z',
  ...overrides,
});

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

  it('registerHomeWidget carries the optional width prop through', () => {
    registerHomeWidget({
      key: 'narrow-default',
      render: () => <span>n</span>,
    });
    registerHomeWidget({
      key: 'wide',
      render: () => <span>w</span>,
      width: 'wide',
    });
    registerHomeWidget({
      key: 'full',
      render: () => <span>f</span>,
      width: 'full',
    });
    const widgets = getHomeWidgets();
    expect(widgets.find((w) => w.key === 'narrow-default')?.width).toBeUndefined();
    expect(widgets.find((w) => w.key === 'wide')?.width).toBe('wide');
    expect(widgets.find((w) => w.key === 'full')?.width).toBe('full');
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
        render: () => <span>first</span>,
      });
      registerRoute({
        key: 'second',
        path: '/x',
        render: () => <span>second</span>,
      });
      const routes = getRoutes();
      expect(routes).toHaveLength(1);
      expect(routes[0]?.key).toBe('second');
      expect(warn).toHaveBeenCalledOnce();
    } finally {
      warn.mockRestore();
    }
  });

  it('registerRoute carries render() through and produces a fresh element each call', () => {
    let calls = 0;
    registerRoute({
      key: 'r',
      path: '/r',
      render: () => {
        calls += 1;
        return <span>r{calls}</span>;
      },
    });
    const route = getRoutes()[0]!;
    expect(typeof route.render).toBe('function');
    const first = route.render!();
    const second = route.render!();
    expect(first).not.toBe(second);
    expect(calls).toBe(2);
  });

  it('registerRoute still accepts deprecated element shape', () => {
    registerRoute({
      key: 'legacy',
      path: '/legacy',
      element: <span>legacy</span>,
    });
    const route = getRoutes()[0]!;
    expect(route.element).toBeDefined();
    expect(route.render).toBeUndefined();
  });

  it('registerRoute drops the registration when neither render nor element is supplied', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      registerRoute({ key: 'broken', path: '/broken' } as never);
      expect(getRoutes()).toHaveLength(0);
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
      render: () => <span>tab</span>,
    });
    const tabs = getAdminTabs();
    expect(tabs[0]?.perm).toBe('thing.manage');
  });

  it('registerAdminTab carries render() through and accepts deprecated element', () => {
    registerAdminTab({
      key: 'a',
      label: 'A',
      render: () => <span>A</span>,
    });
    registerAdminTab({
      key: 'b',
      label: 'B',
      element: <span>B</span>,
    });
    const tabs = getAdminTabs();
    expect(tabs[0]?.render).toBeDefined();
    expect(tabs[0]?.element).toBeUndefined();
    expect(tabs[1]?.render).toBeUndefined();
    expect(tabs[1]?.element).toBeDefined();
  });

  it('registerAdminTab drops the registration when neither render nor element is supplied', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      registerAdminTab({ key: 'broken', label: 'Broken' } as never);
      expect(getAdminTabs()).toHaveLength(0);
      expect(warn).toHaveBeenCalledOnce();
    } finally {
      warn.mockRestore();
    }
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

  it('registerNotificationKind appends entries that getNotificationRenderers returns', () => {
    registerNotificationKind({
      kind: 'block.updated',
      render: () => <span>block</span>,
    });
    registerNotificationKind({
      kind: 'booking.created',
      render: () => <span>booking</span>,
    });
    const entries = getNotificationRenderers();
    expect(entries.map((r) => r.kind)).toEqual([
      'block.updated',
      'booking.created',
    ]);
  });

  it('registerNotificationKind carries optional title and href through', () => {
    registerNotificationKind({
      kind: 'block.updated',
      render: () => <span>block</span>,
      title: (n) => `Block ${(n.payload.block_id as number) ?? '?'} updated`,
      href: (n) => `/calendar?focus=block:${n.payload.block_id ?? ''}`,
    });
    registerNotificationKind({
      kind: 'minimal.kind',
      render: () => <span>minimal</span>,
    });
    const block = lookupNotificationRenderer('block.updated');
    expect(
      block?.title?.(sampleNotification({ payload: { block_id: 7 } })),
    ).toBe('Block 7 updated');
    expect(
      block?.href?.(sampleNotification({ payload: { block_id: 7 } })),
    ).toBe('/calendar?focus=block:7');
    const minimal = lookupNotificationRenderer('minimal.kind');
    expect(minimal?.title).toBeUndefined();
    expect(minimal?.href).toBeUndefined();
  });

  it('registerNotificationKind replaces on duplicate kind with a warning', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      registerNotificationKind({
        kind: 'block.updated',
        render: () => <span>first</span>,
      });
      registerNotificationKind({
        kind: 'block.updated',
        render: () => <span>second</span>,
      });
      const entries = getNotificationRenderers();
      expect(entries).toHaveLength(1);
      // The whole point of last-write-wins is that the second renderer
      // is the live one — exercise it via the lookup.
      const found = lookupNotificationRenderer('block.updated');
      const element = found?.render(sampleNotification());
      const props = element?.props as { children?: string };
      expect(props?.children).toBe('second');
      expect(warn).toHaveBeenCalledOnce();
    } finally {
      warn.mockRestore();
    }
  });

  it('lookupNotificationRenderer returns undefined for an unregistered kind', () => {
    registerNotificationKind({
      kind: 'block.updated',
      render: () => <span>block</span>,
    });
    expect(lookupNotificationRenderer('not.a.kind')).toBeUndefined();
  });

  it('__ATRIUM_REGISTRY__ logs a warning for unknown register* methods without throwing', () => {
    // A host bundle built against a newer atrium that registers a
    // slot this build doesn't ship must not crash mid-import: the
    // earlier registrations would be lost. The Proxy returns a
    // logging shim instead of letting `undefined()` throw.
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      const reg = window.__ATRIUM_REGISTRY__ as unknown as Record<
        string,
        (arg: unknown) => void
      >;
      expect(typeof reg.registerSomethingFromTheFuture).toBe('function');
      reg.registerSomethingFromTheFuture({ key: 'futurey' });
      expect(warn).toHaveBeenCalledOnce();
      const message = String(warn.mock.calls[0]?.[0] ?? '');
      expect(message).toContain('registerSomethingFromTheFuture');
      expect(message).toContain('futurey');
      // The bundle's later calls still land — that's the whole point.
      registerHomeWidget({
        key: 'after-future-call',
        render: () => <span>ok</span>,
      });
      expect(getHomeWidgets().map((w) => w.key)).toContain(
        'after-future-call',
      );
    } finally {
      warn.mockRestore();
    }
  });

  it('registerLocale records overlays and notifies subscribers', () => {
    const heard: string[] = [];
    const off = subscribeLocaleOverlay((o) => heard.push(o.locale));
    try {
      registerLocale({ locale: 'en', strings: { 'app.title': 'X' } });
      registerLocale({ locale: 'nl', strings: { 'app.title': 'X-NL' } });
      const overlays = getLocaleOverlays();
      expect(overlays.map((o) => o.locale)).toEqual(['en', 'nl']);
      expect(heard).toEqual(['en', 'nl']);
    } finally {
      off();
    }
  });

  it('registerLocale stacks multiple overlays for the same locale in order', () => {
    registerLocale({ locale: 'en', strings: { 'a': '1' } });
    registerLocale({ locale: 'en', strings: { 'b': '2' } });
    expect(getLocaleOverlays()).toHaveLength(2);
  });

  it('registerLocale rejects empty locale and non-object strings', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      registerLocale({ locale: '', strings: { a: '1' } });
      registerLocale({ locale: 'en', strings: null as unknown as Record<string, unknown> });
      registerLocale({ locale: 'en', strings: ['a'] as unknown as Record<string, unknown> });
      expect(getLocaleOverlays()).toHaveLength(0);
      expect(warn).toHaveBeenCalledTimes(3);
    } finally {
      warn.mockRestore();
    }
  });

  it('subscribeEvent on the registry routes to the event bus', () => {
    // The registry just re-exports the bus's subscribe helper; this
    // pins down that __ATRIUM_REGISTRY__.subscribeEvent shares state
    // with the standalone export, so a host bundle calling either one
    // lands in the same fan-out.
    const handler = vi.fn();
    const off = subscribeEvent('booking.created', handler);
    expect(__eventBusSubscriberCountForTests('booking.created')).toBe(1);
    dispatchAtriumEvent({ kind: 'booking.created', payload: { id: 1 } });
    expect(handler).toHaveBeenCalledOnce();
    off();
    expect(__eventBusSubscriberCountForTests('booking.created')).toBe(0);
  });

  it('__ATRIUM_REGISTRY__.subscribeEvent is the same helper', () => {
    const reg = window.__ATRIUM_REGISTRY__!;
    const handler = vi.fn();
    const off = reg.subscribeEvent('block.updated', handler);
    dispatchAtriumEvent({ kind: 'block.updated', payload: { id: 7 } });
    expect(handler).toHaveBeenCalledWith({
      kind: 'block.updated',
      payload: { id: 7 },
    });
    off();
  });

  it('__resetRegistryForTests also clears event bus subscriptions', () => {
    subscribeEvent('block.updated', () => {});
    expect(__eventBusSubscriberCountForTests('block.updated')).toBe(1);
    __resetRegistryForTests();
    expect(__eventBusSubscriberCountForTests('block.updated')).toBe(0);
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
