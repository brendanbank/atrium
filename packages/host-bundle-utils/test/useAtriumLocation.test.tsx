// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Vitest coverage for ``useAtriumLocation()``.
 *
 * The hook bridges atrium's ``atrium:locationchange`` window event into
 * a host bundle's React tree via ``useSyncExternalStore``. Tests pin
 * down: initial snapshot reads ``window.location``, dispatched events
 * update the snapshot and trigger a re-render, and multiple subscribers
 * share one cached snapshot (no tear-loop, no per-render reallocation).
 */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import React from 'react';
import { act, cleanup, render, screen } from '@testing-library/react';

import {
  __resetAtriumLocationCacheForTests,
  useAtriumLocation,
  useAtriumNavigate,
  type AtriumLocation,
} from '../src/react/index';

let _testNonce = 0;

function dispatchAtriumLocation(
  detail: Omit<AtriumLocation, 'nonce'> & { nonce?: number },
): void {
  const nonce = detail.nonce ?? ++_testNonce;
  window.dispatchEvent(
    new CustomEvent<AtriumLocation>('atrium:locationchange', {
      detail: { ...detail, nonce },
    }),
  );
}

function LocationProbe({ id }: { id: string }) {
  const loc = useAtriumLocation();
  return (
    <span data-testid={id}>
      {loc.pathname}|{loc.search}|{loc.hash}
    </span>
  );
}

describe('useAtriumLocation', () => {
  beforeEach(() => {
    __resetAtriumLocationCacheForTests();
    _testNonce = 0;
  });

  afterEach(() => {
    cleanup();
    __resetAtriumLocationCacheForTests();
  });

  test('initial snapshot reflects window.location at first render', () => {
    // jsdom's default URL is `about:blank` whose pathname is `/blank`
    // (or `/` depending on the jsdom version) — we only assert the
    // shape and that all three fields are strings, since the actual
    // value isn't load-bearing for the test.
    render(<LocationProbe id="loc" />);
    const txt = screen.getByTestId('loc').textContent ?? '';
    const parts = txt.split('|');
    expect(parts).toHaveLength(3);
    expect(typeof parts[0]).toBe('string');
    expect(typeof parts[1]).toBe('string');
    expect(typeof parts[2]).toBe('string');
  });

  test('dispatched event updates the snapshot and re-renders', () => {
    render(<LocationProbe id="loc" />);

    act(() => {
      dispatchAtriumLocation({
        pathname: '/',
        search: '?focus=booking:42',
        hash: '',
      });
    });

    expect(screen.getByTestId('loc').textContent).toBe('/|?focus=booking:42|');
  });

  test('hash-only change re-renders', () => {
    render(<LocationProbe id="loc" />);

    act(() => {
      dispatchAtriumLocation({
        pathname: '/profile',
        search: '',
        hash: '#sessions',
      });
    });

    expect(screen.getByTestId('loc').textContent).toBe('/profile||#sessions');
  });

  test('multiple subscribers share one cached snapshot', () => {
    render(
      <>
        <LocationProbe id="a" />
        <LocationProbe id="b" />
        <LocationProbe id="c" />
      </>,
    );

    act(() => {
      dispatchAtriumLocation({
        pathname: '/admin',
        search: '?tab=branding',
        hash: '',
      });
    });

    const expected = '/admin|?tab=branding|';
    expect(screen.getByTestId('a').textContent).toBe(expected);
    expect(screen.getByTestId('b').textContent).toBe(expected);
    expect(screen.getByTestId('c').textContent).toBe(expected);
  });

  test('falls back to window.location when event detail is missing', () => {
    render(<LocationProbe id="loc" />);

    // Seed a known snapshot via a well-formed event so the cache holds
    // a non-default value.
    act(() => {
      dispatchAtriumLocation({
        pathname: '/seed',
        search: '?x=1',
        hash: '',
      });
    });
    expect(screen.getByTestId('loc').textContent).toBe('/seed|?x=1|');

    // A bare event with no detail must trigger a refresh from
    // window.location (whatever jsdom reports), wiping the seeded
    // pathname. We assert the refreshed snapshot is no longer the
    // seeded one.
    act(() => {
      window.dispatchEvent(new Event('atrium:locationchange'));
    });
    expect(screen.getByTestId('loc').textContent).not.toBe('/seed|?x=1|');
  });

  test('subsequent renders reuse the cached snapshot reference', () => {
    let observed = 0;
    function CountingProbe() {
      const loc = useAtriumLocation();
      observed += 1;
      return <span data-testid="count">{loc.pathname}</span>;
    }
    const { rerender } = render(<CountingProbe />);
    const before = observed;

    // A re-render with no event in between must not cause additional
    // store reads to produce a fresh object — the cached snapshot is
    // referentially stable, so React doesn't tear-loop.
    rerender(<CountingProbe />);
    rerender(<CountingProbe />);
    rerender(<CountingProbe />);

    // Three explicit re-renders → three runs of the body, no infinite
    // loop. (Without referential stability React would throw "Maximum
    // update depth exceeded".)
    expect(observed - before).toBe(3);
  });

  test('snapshot carries the dispatched nonce so identical-URL events still re-render (#81)', () => {
    let observedNonces: number[] = [];
    function NonceProbe() {
      const loc = useAtriumLocation();
      observedNonces.push(loc.nonce);
      return null;
    }
    render(<NonceProbe />);
    observedNonces = [];

    // Two events with the same {pathname, search, hash} but different
    // nonces must each produce a distinct snapshot, so a host effect
    // depending on nonce re-runs both times.
    act(() => {
      dispatchAtriumLocation({
        pathname: '/',
        search: '?focus=booking:42',
        hash: '',
        nonce: 7,
      });
    });
    act(() => {
      dispatchAtriumLocation({
        pathname: '/',
        search: '?focus=booking:42',
        hash: '',
        nonce: 8,
      });
    });

    expect(observedNonces).toContain(7);
    expect(observedNonces).toContain(8);
  });

  test('defaults nonce to 0 when the event detail lacks one (older atrium image)', () => {
    let observed: number | undefined;
    function NonceProbe() {
      const loc = useAtriumLocation();
      observed = loc.nonce;
      return null;
    }
    render(<NonceProbe />);

    // Pre-0.16 atrium dispatched the event without a `nonce` field.
    // Cast through `unknown` so we can simulate that wire shape.
    act(() => {
      window.dispatchEvent(
        new CustomEvent('atrium:locationchange', {
          detail: { pathname: '/legacy', search: '', hash: '' } as unknown,
        }),
      );
    });

    expect(observed).toBe(0);
  });

  test('useAtriumNavigate pushState + popstate updates window.location and fires atrium:locationchange via the host listener', () => {
    let navigate: ReturnType<typeof useAtriumNavigate> | null = null;
    function NavProbe() {
      navigate = useAtriumNavigate();
      return null;
    }
    render(<NavProbe />);

    // Capture popstate dispatched by the navigate helper. We don't
    // assert atrium:locationchange firing here because that's atrium's
    // NavigationBridge job (covered in frontend/src/test/host-navigation.test);
    // we only need to confirm the helper updates window.location and
    // dispatches the popstate that wires react-router back into sync.
    const pops: PopStateEvent[] = [];
    const onPop = (e: Event) => {
      pops.push(e as PopStateEvent);
    };
    window.addEventListener('popstate', onPop);

    const origin = window.location.origin;
    act(() => {
      navigate!('/booked?focus=42');
    });

    expect(window.location.pathname).toBe('/booked');
    expect(window.location.search).toBe('?focus=42');
    expect(pops.length).toBeGreaterThanOrEqual(1);

    // replace mode preserves the same history depth but still rewrites
    // the URL and re-fires popstate.
    act(() => {
      navigate!('/booked', { replace: true });
    });
    expect(window.location.pathname).toBe('/booked');
    expect(window.location.search).toBe('');

    window.removeEventListener('popstate', onPop);
    // jsdom doesn't reset window.location between tests; restore so
    // later tests in this file see a clean slate.
    window.history.replaceState({}, '', origin + '/');
  });

  test('unsubscribes on unmount', () => {
    const { unmount } = render(<LocationProbe id="loc" />);
    unmount();

    // After unmount the listener is gone; a fresh probe still works,
    // confirming subscribe/unsubscribe parity. If subscribe leaked,
    // jsdom would accumulate listeners and re-mount paths would still
    // pass — so this is a smoke test that nothing throws on a fresh
    // mount cycle.
    __resetAtriumLocationCacheForTests();
    render(<LocationProbe id="loc2" />);
    act(() => {
      dispatchAtriumLocation({
        pathname: '/calendar',
        search: '',
        hash: '',
      });
    });
    expect(screen.getByTestId('loc2').textContent).toBe('/calendar||');
  });
});
