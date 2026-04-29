// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Vitest coverage for the navigation bridge.
 *
 * Pins down the contract host bundles rely on: every commit to atrium's
 * router fires one ``atrium:locationchange`` CustomEvent on ``window``
 * carrying the new ``{pathname, search, hash}`` triple, including the
 * in-place case (``navigate(href)`` while already on the matched route)
 * which is the whole point of the bridge — see #77.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { useEffect } from 'react';
import { render, act, cleanup } from '@testing-library/react';
import { MemoryRouter, useNavigate } from 'react-router-dom';

import {
  ATRIUM_LOCATION_EVENT,
  NavigationBridge,
  __resetNavigationNonceForTests,
  announceCurrentLocation,
  dispatchLocationChange,
  type AtriumLocationDetail,
} from '@/host/navigation';

type Capture = AtriumLocationDetail[];

function captureEvents(): { events: Capture; off: () => void } {
  const events: Capture = [];
  const handler = (e: Event) => {
    const detail = (e as CustomEvent<AtriumLocationDetail>).detail;
    events.push({ ...detail });
  };
  window.addEventListener(ATRIUM_LOCATION_EVENT, handler);
  return {
    events,
    off: () => window.removeEventListener(ATRIUM_LOCATION_EVENT, handler),
  };
}

function Navigator({ to }: { to: string }) {
  const navigate = useNavigate();
  useEffect(() => {
    navigate(to);
  }, [navigate, to]);
  return null;
}

describe('NavigationBridge', () => {
  beforeEach(() => {
    cleanup();
    __resetNavigationNonceForTests();
  });

  it('fires atrium:locationchange on initial mount', () => {
    const cap = captureEvents();
    try {
      render(
        <MemoryRouter initialEntries={['/calendar']}>
          <NavigationBridge />
        </MemoryRouter>,
      );
      expect(cap.events).toHaveLength(1);
      expect(cap.events[0]).toEqual({
        pathname: '/calendar',
        search: '',
        hash: '',
        nonce: 1,
      });
    } finally {
      cap.off();
    }
  });

  it('fires on programmatic navigation that crosses paths', async () => {
    const cap = captureEvents();
    try {
      const { rerender } = render(
        <MemoryRouter initialEntries={['/']}>
          <NavigationBridge />
          <Navigator to="/" />
        </MemoryRouter>,
      );
      // Initial mount: one event for "/".
      expect(cap.events.map((e) => e.pathname)).toEqual(['/']);

      await act(async () => {
        rerender(
          <MemoryRouter initialEntries={['/']}>
            <NavigationBridge />
            <Navigator to="/calendar" />
          </MemoryRouter>,
        );
      });

      // Re-rendering with a new MemoryRouter starts a fresh router —
      // bridge re-mounts at /calendar and fires once for the new path.
      const paths = cap.events.map((e) => e.pathname);
      expect(paths).toContain('/calendar');
    } finally {
      cap.off();
    }
  });

  it('fires when the search string changes on the same path (the issue #77 case)', async () => {
    // Reproduces the bug: clicking a notification whose href is
    // `/?focus=booking:42` while already on `/` updates the URL via
    // pushState; popstate doesn't fire, but the bridge dispatches.
    const cap = captureEvents();
    try {
      const navRef: { current: ((to: string) => void) | null } = {
        current: null,
      };
      function CaptureNav() {
        const nav = useNavigate();
        useEffect(() => {
          navRef.current = nav;
        }, [nav]);
        return null;
      }
      render(
        <MemoryRouter initialEntries={['/']}>
          <NavigationBridge />
          <CaptureNav />
        </MemoryRouter>,
      );
      cap.events.length = 0;

      await act(async () => {
        navRef.current?.('/?focus=booking:42');
      });

      expect(cap.events).toHaveLength(1);
      expect(cap.events[0].pathname).toBe('/');
      expect(cap.events[0].search).toBe('?focus=booking:42');
      expect(cap.events[0].hash).toBe('');
      expect(typeof cap.events[0].nonce).toBe('number');
    } finally {
      cap.off();
    }
  });

  it('attaches a monotonically-increasing nonce to every event (#81)', () => {
    const cap = captureEvents();
    try {
      // The bridge fires once on mount; each subsequent dispatch
      // (whether via the bridge effect or via announceCurrentLocation)
      // must increment the nonce so a host that depends on it in
      // effect deps re-runs even when pathname/search/hash are
      // structurally identical between consecutive events.
      dispatchLocationChange({ pathname: '/', search: '', hash: '' });
      dispatchLocationChange({ pathname: '/', search: '', hash: '' });
      announceCurrentLocation();

      const nonces = cap.events.map((e) => e.nonce);
      expect(nonces.length).toBe(3);
      expect(nonces[1]).toBeGreaterThan(nonces[0]);
      expect(nonces[2]).toBeGreaterThan(nonces[1]);
    } finally {
      cap.off();
    }
  });

  it('fires for hash changes', async () => {
    const cap = captureEvents();
    try {
      const navRef: { current: ((to: string) => void) | null } = {
        current: null,
      };
      function CaptureNav() {
        const nav = useNavigate();
        useEffect(() => {
          navRef.current = nav;
        }, [nav]);
        return null;
      }
      render(
        <MemoryRouter initialEntries={['/profile']}>
          <NavigationBridge />
          <CaptureNav />
        </MemoryRouter>,
      );
      cap.events.length = 0;

      await act(async () => {
        navRef.current?.('/profile#sessions');
      });

      expect(cap.events).toHaveLength(1);
      expect(cap.events[0].hash).toBe('#sessions');
    } finally {
      cap.off();
    }
  });
});
