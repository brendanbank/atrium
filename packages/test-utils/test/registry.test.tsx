// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { cleanup, screen, waitFor } from '@testing-library/react';

import {
  fireAtriumEvent,
  mockAtriumRegistry,
  renderWithAtrium,
  type MockAtriumHandles,
  type UserContext,
} from '../src/index';
import {
  __atrium_t__,
  useMe,
  usePerm,
} from '@brendanbank/atrium-host-bundle-utils/react';

const ALICE: UserContext = {
  id: 7,
  email: 'alice@example.com',
  full_name: 'Alice Example',
  is_active: true,
  roles: ['admin'],
  permissions: ['hello.toggle', 'audit.read'],
  impersonating_from: null,
};

let handles: MockAtriumHandles;

beforeEach(() => {
  handles = mockAtriumRegistry({ me: ALICE });
});

afterEach(() => {
  cleanup();
  handles.cleanup();
});

describe('mockAtriumRegistry', () => {
  test('records register* calls so a host bundle can be asserted against', () => {
    handles.registry.registerHomeWidget({
      key: 'hello',
      render: () => null as unknown as React.ReactElement,
    });
    handles.registry.registerNavItem({ key: 'nav', label: 'Hi', to: '/hi' });
    handles.registry.registerAdminTab({
      key: 'tab',
      label: 'Tab',
      perm: 'audit.read',
      render: () => null as unknown as React.ReactElement,
    });

    expect(handles.homeWidgets).toHaveLength(1);
    expect(handles.homeWidgets[0].key).toBe('hello');
    expect(handles.navItems).toHaveLength(1);
    expect(handles.adminTabs).toHaveLength(1);
  });

  test('installs window.__ATRIUM_REGISTRY__ pointing at the same fake', () => {
    expect(window.__ATRIUM_REGISTRY__).toBe(handles.registry);
  });

  test('exposes window.React so makeWrapperElement resolves', () => {
    expect((window as unknown as { React?: unknown }).React).toBeDefined();
  });

  test('cleanup restores the pre-mock window state', () => {
    handles.cleanup();
    expect(window.__ATRIUM_REGISTRY__).toBeUndefined();
  });

  test('reset clears recorded registrations and subscribers', () => {
    handles.registry.registerHomeWidget({
      key: 'a',
      render: () => null as unknown as React.ReactElement,
    });
    handles.registry.subscribeEvent('foo', () => {});
    handles.reset();
    expect(handles.homeWidgets).toEqual([]);
    let fired = 0;
    handles.registry.subscribeEvent('foo', () => {
      fired += 1;
    });
    fireAtriumEvent('foo', {});
    expect(fired).toBe(1);
  });
});

describe('useMe via renderWithAtrium', () => {
  function MeProbe() {
    const { data, isLoading } = useMe();
    if (isLoading) return <span>loading</span>;
    if (!data) return <span>signed-out</span>;
    return <span data-testid="email">{data.email}</span>;
  }

  test('returns the configured me to useMe()', async () => {
    renderWithAtrium(<MeProbe />);
    await waitFor(() =>
      expect(screen.getByTestId('email').textContent).toBe(
        'alice@example.com',
      ),
    );
  });

  test('per-render me override wins over the registry default', async () => {
    renderWithAtrium(<MeProbe />, {
      me: { ...ALICE, email: 'bob@example.com' },
    });
    await waitFor(() =>
      expect(screen.getByTestId('email').textContent).toBe('bob@example.com'),
    );
  });

  test('signed-out renders when me=null', async () => {
    handles.cleanup();
    handles = mockAtriumRegistry({ me: null });
    renderWithAtrium(<MeProbe />);
    await waitFor(() =>
      expect(screen.getByText('signed-out')).toBeInTheDocument(),
    );
  });
});

describe('usePerm via renderWithAtrium', () => {
  function PermProbe({ code }: { code: string }) {
    const hasPerm = usePerm();
    return (
      <span data-testid={`perm-${code}`}>{hasPerm(code) ? 'yes' : 'no'}</span>
    );
  }

  test('returns true for permissions on the configured me', async () => {
    renderWithAtrium(<PermProbe code="hello.toggle" />);
    await waitFor(() =>
      expect(screen.getByTestId('perm-hello.toggle').textContent).toBe('yes'),
    );
  });

  test('returns false for permissions the user lacks', async () => {
    renderWithAtrium(<PermProbe code="user.manage" />);
    await waitFor(() =>
      expect(screen.getByTestId('perm-user.manage').textContent).toBe('no'),
    );
  });
});

describe('fireAtriumEvent', () => {
  test('dispatches to handlers registered via the fake registry', () => {
    const seen: Array<{ kind: string; payload: Record<string, unknown> }> = [];
    handles.registry.subscribeEvent('booking.created', (e) => {
      seen.push(e);
    });
    fireAtriumEvent('booking.created', { booking_id: 42 });
    expect(seen).toEqual([
      { kind: 'booking.created', payload: { booking_id: 42 } },
    ]);
  });

  test('only fires handlers matching the kind', () => {
    let aHits = 0;
    let bHits = 0;
    handles.registry.subscribeEvent('a', () => {
      aHits += 1;
    });
    handles.registry.subscribeEvent('b', () => {
      bHits += 1;
    });
    fireAtriumEvent('a', {});
    expect(aHits).toBe(1);
    expect(bHits).toBe(0);
  });

  test('unsubscribe stops further dispatches', () => {
    let hits = 0;
    const off = handles.registry.subscribeEvent('x', () => {
      hits += 1;
    });
    fireAtriumEvent('x', {});
    off();
    fireAtriumEvent('x', {});
    expect(hits).toBe(1);
  });

  test('handler that unsubscribes mid-fire does not skip a sibling', () => {
    let aHits = 0;
    let bHits = 0;
    let offA: (() => void) | null = null;
    offA = handles.registry.subscribeEvent('shared', () => {
      aHits += 1;
      offA?.();
    });
    handles.registry.subscribeEvent('shared', () => {
      bHits += 1;
    });
    fireAtriumEvent('shared', {});
    expect(aHits).toBe(1);
    expect(bHits).toBe(1);
  });

  test('no-op when called outside a mockAtriumRegistry scope', () => {
    handles.cleanup();
    expect(() => fireAtriumEvent('any', {})).not.toThrow();
  });
});

describe('window.__atrium_i18n__ + __atrium_t__', () => {
  test('resolves bundled common.* keys to English by default', () => {
    expect(__atrium_t__('common.save')).toBe('Save');
    expect(__atrium_t__('common.cancel')).toBe('Cancel');
  });

  test('falls back to English when active locale lacks the key', () => {
    handles.cleanup();
    handles = mockAtriumRegistry({
      i18n: {
        resources: {
          en: { 'common.save': 'Save' },
          nl: {},
        },
        language: 'nl',
      },
    });
    expect(__atrium_t__('common.save')).toBe('Save');
  });

  test('returns the literal key when nothing matches', () => {
    handles.cleanup();
    handles = mockAtriumRegistry({
      i18n: { resources: { en: {} } },
    });
    expect(__atrium_t__('common.unknownKey')).toBe('common.unknownKey');
  });
});
