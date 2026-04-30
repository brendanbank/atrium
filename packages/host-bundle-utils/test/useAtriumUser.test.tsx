// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Vitest coverage for ``useAtriumUser()``.
 *
 * The hook bridges atrium's ``atrium:userchange`` window event into a
 * host bundle's React tree via ``useSyncExternalStore``. Tests pin
 * down: the initial snapshot is the zeroed sentinel until the first
 * event lands, dispatched events update the snapshot and trigger a
 * re-render, multiple subscribers share one cached snapshot, and the
 * cache survives unmount/remount cycles.
 */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { act, cleanup, render, screen } from '@testing-library/react';

import {
  __resetAtriumUserCacheForTests,
  useAtriumUser,
  type AtriumUserChangeDetail,
} from '../src/react/index';

let _testNonce = 0;

function dispatchAtriumUser(
  detail: Omit<AtriumUserChangeDetail, 'nonce'> & { nonce?: number },
): void {
  const nonce = detail.nonce ?? ++_testNonce;
  window.dispatchEvent(
    new CustomEvent<AtriumUserChangeDetail>('atrium:userchange', {
      detail: { ...detail, nonce },
    }),
  );
}

function UserProbe({ id }: { id: string }) {
  const evt = useAtriumUser();
  return (
    <span data-testid={id}>
      {String(evt.previous)}|{String(evt.current)}|{evt.nonce}
    </span>
  );
}

describe('useAtriumUser', () => {
  beforeEach(() => {
    __resetAtriumUserCacheForTests();
    _testNonce = 0;
  });

  afterEach(() => {
    cleanup();
    __resetAtriumUserCacheForTests();
  });

  test('initial snapshot is the zeroed sentinel before any event', () => {
    render(<UserProbe id="u" />);
    // No event has fired — host hooks see {previous: null, current:
    // null, nonce: 0}, which the host code keys off as "no transition
    // observed yet, do nothing". A page reload of an already-signed-in
    // tab must not look like a logout.
    expect(screen.getByTestId('u').textContent).toBe('null|null|0');
  });

  test('dispatched event updates the snapshot and re-renders', () => {
    render(<UserProbe id="u" />);

    act(() => {
      dispatchAtriumUser({ previous: null, current: 7 });
    });

    expect(screen.getByTestId('u').textContent).toBe('null|7|1');
  });

  test('user → null logout transition is observable', () => {
    render(<UserProbe id="u" />);

    act(() => {
      dispatchAtriumUser({ previous: 7, current: null });
    });

    expect(screen.getByTestId('u').textContent).toBe('7|null|1');
  });

  test('user → user same-tab swap is observable', () => {
    render(<UserProbe id="u" />);

    act(() => {
      dispatchAtriumUser({ previous: 7, current: 11 });
    });

    expect(screen.getByTestId('u').textContent).toBe('7|11|1');
  });

  test('multiple subscribers share one cached snapshot', () => {
    render(
      <>
        <UserProbe id="a" />
        <UserProbe id="b" />
        <UserProbe id="c" />
      </>,
    );

    act(() => {
      dispatchAtriumUser({ previous: 1, current: 42 });
    });

    const expected = '1|42|1';
    expect(screen.getByTestId('a').textContent).toBe(expected);
    expect(screen.getByTestId('b').textContent).toBe(expected);
    expect(screen.getByTestId('c').textContent).toBe(expected);
  });

  test('ignores malformed events with missing detail fields', () => {
    render(<UserProbe id="u" />);

    // A bare event without a usable detail must NOT touch the cache —
    // hosts that key off `nonce` to fire a one-shot effect would
    // otherwise see a phantom transition.
    act(() => {
      window.dispatchEvent(new Event('atrium:userchange'));
    });
    expect(screen.getByTestId('u').textContent).toBe('null|null|0');

    act(() => {
      window.dispatchEvent(
        new CustomEvent('atrium:userchange', {
          detail: { previous: 'not-a-number' } as unknown,
        }),
      );
    });
    expect(screen.getByTestId('u').textContent).toBe('null|null|0');
  });

  test('snapshot carries the dispatched nonce', () => {
    let observed: number[] = [];
    function NonceProbe() {
      observed.push(useAtriumUser().nonce);
      return null;
    }
    render(<NonceProbe />);
    observed = [];

    act(() => {
      dispatchAtriumUser({ previous: null, current: 1, nonce: 7 });
    });
    act(() => {
      dispatchAtriumUser({ previous: 1, current: null, nonce: 8 });
    });

    expect(observed).toContain(7);
    expect(observed).toContain(8);
  });

  test('defaults nonce to 0 when the event detail lacks one', () => {
    let observed: number | undefined;
    function NonceProbe() {
      observed = useAtriumUser().nonce;
      return null;
    }
    render(<NonceProbe />);

    // Older atrium images may dispatch without a nonce field; the hook
    // still applies the previous/current values and falls back to 0.
    act(() => {
      window.dispatchEvent(
        new CustomEvent('atrium:userchange', {
          detail: { previous: null, current: 7 } as unknown,
        }),
      );
    });

    expect(observed).toBe(0);
  });

  test('unsubscribes on unmount, fresh mount still works', () => {
    const { unmount } = render(<UserProbe id="u" />);
    unmount();

    __resetAtriumUserCacheForTests();
    render(<UserProbe id="u2" />);
    act(() => {
      dispatchAtriumUser({ previous: null, current: 99 });
    });
    expect(screen.getByTestId('u2').textContent).toBe('null|99|1');
  });
});
