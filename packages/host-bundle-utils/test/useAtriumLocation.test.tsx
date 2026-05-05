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

  test('native popstate refreshes the snapshot from window.location (#134)', () => {
    // Browser back/forward does not go through `useAtriumNavigate`, so
    // no `atrium:locationchange` fires. Without a popstate listener the
    // module-level cache would stay pinned to whatever the previous
    // atrium-mediated nav set, causing host bundles that derive route
    // state from `useAtriumLocation().pathname` to render the previous
    // URL's content (e.g. `/people/7` instead of `/people/6` after a
    // back-then-click).
    const origin = window.location.origin;
    render(<LocationProbe id="loc" />);

    // Seed a known cache value via a well-formed atrium event.
    act(() => {
      dispatchAtriumLocation({
        pathname: '/people/7',
        search: '',
        hash: '',
      });
    });
    expect(screen.getByTestId('loc').textContent).toBe('/people/7||');

    // Simulate browser back: rewrite window.location directly (bypassing
    // useAtriumNavigate so no atrium:locationchange fires) and dispatch
    // a native popstate. The hook must re-read window.location.
    act(() => {
      window.history.replaceState({}, '', `${origin}/people`);
      window.dispatchEvent(new PopStateEvent('popstate'));
    });
    expect(screen.getByTestId('loc').textContent).toBe('/people||');

    // Restore for later tests.
    window.history.replaceState({}, '', `${origin}/`);
  });

  test('atrium event detail wins over window.location when both fire (#134)', () => {
    // Sanity-check the listener ordering: an atrium:locationchange that
    // arrives with a structured detail (the normal nav path) must use
    // the detail, not fall back to window.location. This is the
    // existing contract; the popstate listener addition must not break
    // it.
    const origin = window.location.origin;
    render(<LocationProbe id="loc" />);

    act(() => {
      // Window.location says /raw, but atrium's detail says /detail.
      window.history.replaceState({}, '', `${origin}/raw`);
      dispatchAtriumLocation({
        pathname: '/detail',
        search: '?from=event',
        hash: '',
      });
    });
    expect(screen.getByTestId('loc').textContent).toBe('/detail|?from=event|');

    window.history.replaceState({}, '', `${origin}/`);
  });

  test('fresh subscriber after a subscriber-less window reads current window.location, not the stale cache (#137)', () => {
    // Repro: detail-page A mounts → subscribes → cache holds /people/7.
    // Browser-back unmounts A and the popstate refresh leaves the cache
    // at /people. A click then navigates to /people/6 via
    // useAtriumNavigate, which dispatches atrium:locationchange — but no
    // host-side subscriber is attached during that window, so the cache
    // stays at /people. Detail-page B mounts; without the subscribe-time
    // refresh it would read /people from the cache and render the wrong
    // id.
    const origin = window.location.origin;

    // Step 1: page A subscribes and the cache holds /people/7.
    const a = render(<LocationProbe id="a" />);
    act(() => {
      dispatchAtriumLocation({
        pathname: '/people/7',
        search: '',
        hash: '',
      });
    });
    expect(screen.getByTestId('a').textContent).toBe('/people/7||');

    // Step 2: page A unmounts (subscriber-less from here).
    a.unmount();

    // Step 3: window.location changes to /people/6 while no subscriber
    // is attached. We rewrite directly to simulate a navigation that the
    // host bundle missed (the atrium:locationchange detail or popstate
    // fired into the void).
    window.history.replaceState({}, '', `${origin}/people/6`);

    // Step 4: page B mounts and must observe /people/6, not the stale
    // /people/7 the cache still holds.
    render(<LocationProbe id="b" />);
    expect(screen.getByTestId('b').textContent).toBe('/people/6||');

    window.history.replaceState({}, '', `${origin}/`);
  });

  test('subscribe-time refresh also covers a missed atrium:locationchange (no popstate)', () => {
    // Same as above but the missed event was an atrium:locationchange
    // dispatched by useAtriumNavigate while no subscriber was attached.
    // We can't dispatch the event into a void and have it move
    // window.location (jsdom doesn't intercept the synthesized popstate
    // the way a real browser would), so we emulate the post-conditions:
    // window.location moved, and the cache still holds the previous URL
    // because the listener wasn't attached.
    const origin = window.location.origin;

    // Seed cache to a known stale value via a well-formed event.
    const a = render(<LocationProbe id="a" />);
    act(() => {
      dispatchAtriumLocation({
        pathname: '/people',
        search: '',
        hash: '',
      });
    });
    expect(screen.getByTestId('a').textContent).toBe('/people||');
    a.unmount();

    // While no subscriber is attached, navigation lands the URL at
    // /people/6. (popstate did not fire — this is the navigate path.)
    window.history.replaceState({}, '', `${origin}/people/6`);

    render(<LocationProbe id="b" />);
    expect(screen.getByTestId('b').textContent).toBe('/people/6||');

    window.history.replaceState({}, '', `${origin}/`);
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
