// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import React, { type ReactElement } from 'react';
import { act } from '@testing-library/react';

// Stand in for `window.React` — atrium exposes its own React on the
// global so host bundles can `createElement` atrium-React elements
// without bundling a second React copy. The dual-tree pattern relies
// on this — see `frontend/src/main.tsx`. The package reads `window.React`
// at call time, so installing it in `beforeEach` is enough.
import { makeWrapperElement, mountInside, unmountInside } from '../src/index';

declare global {
  interface Window {
    React?: typeof React;
  }
}

beforeEach(() => {
  window.React = React;
});

afterEach(() => {
  delete window.React;
  document.body.innerHTML = '';
  // Drain any pending React.act() work so a previous test's pending
  // root teardown doesn't bleed into the next.
  return new Promise<void>((resolve) => setTimeout(resolve, 0));
});

function attachWrapper(child: ReactElement): HTMLDivElement {
  // makeWrapperElement returns an atrium-React element. In a real
  // host atrium's reconciler renders it; in the test we mimic that
  // by extracting the ref callback and invoking it with a fresh DOM
  // node, which is exactly what the reconciler does on commit.
  const wrapper = makeWrapperElement(child) as {
    props: { ref: (el: HTMLElement | null) => void };
  };
  const slot = document.createElement('div');
  document.body.appendChild(slot);
  act(() => {
    wrapper.props.ref(slot);
  });
  return slot as HTMLDivElement;
}

describe('mountInside', () => {
  test('mounts the host React tree into the slot element', () => {
    const slot = document.createElement('div');
    document.body.appendChild(slot);

    act(() => {
      mountInside(slot, <p data-testid="child">hello</p>);
    });

    expect(slot.querySelector('p')).not.toBeNull();
    expect(slot.querySelector('p')?.textContent).toBe('hello');
  });

  test('is idempotent on the same el+child reference', () => {
    const slot = document.createElement('div');
    document.body.appendChild(slot);
    const child = <p data-testid="child">a</p>;

    act(() => {
      mountInside(slot, child);
    });
    const first = slot.querySelector('p');

    act(() => {
      mountInside(slot, child);
    });
    const second = slot.querySelector('p');

    // Same DOM node — no re-render.
    expect(second).toBe(first);
    expect(slot.querySelectorAll('p')).toHaveLength(1);
  });

  test('re-renders into the existing root when child swaps', () => {
    const slot = document.createElement('div');
    document.body.appendChild(slot);

    act(() => {
      mountInside(slot, <p>first</p>);
    });
    expect(slot.textContent).toBe('first');

    act(() => {
      mountInside(slot, <p>second</p>);
    });
    expect(slot.textContent).toBe('second');
    // Single root, single tree — no leaked siblings from the prior child.
    expect(slot.querySelectorAll('p')).toHaveLength(1);
  });

  test('unmountInside tears the root down', () => {
    const slot = document.createElement('div');
    document.body.appendChild(slot);
    act(() => {
      mountInside(slot, <p>x</p>);
    });
    expect(slot.querySelector('p')).not.toBeNull();

    act(() => {
      unmountInside(slot);
    });
    expect(slot.querySelector('p')).toBeNull();
  });
});

describe('makeWrapperElement', () => {
  test('throws a clear error when window.React is missing', () => {
    delete window.React;
    expect(() => makeWrapperElement(<p>x</p>)).toThrow(
      /window\.React is missing/,
    );
  });

  test('mounts the child when atrium ref-callbacks the slot', () => {
    const slot = attachWrapper(<p data-testid="hello">hi</p>);
    expect(slot.querySelector('p')?.textContent).toBe('hi');
  });

  test('child swap across separate makeWrapperElement calls does not leak the previous tree', () => {
    // Issue #31: two `<Route>` registrations with structurally identical
    // wrapper divs share the same DOM node when react-router swaps
    // between them. Each call captures its own child via closure;
    // when the second wrapper's ref fires on the same slot, the
    // first wrapper's ref should have fired with `null` first,
    // unmounting that root cleanly.
    const wrapperA = makeWrapperElement(<p>route-A</p>) as {
      props: { ref: (el: HTMLElement | null) => void };
    };
    const wrapperB = makeWrapperElement(<p>route-B</p>) as {
      props: { ref: (el: HTMLElement | null) => void };
    };

    const slot = document.createElement('div');
    document.body.appendChild(slot);

    act(() => {
      wrapperA.props.ref(slot);
    });
    expect(slot.textContent).toBe('route-A');

    // React would call A's ref with null when the route is removed,
    // then B's ref with the new (or reused) DOM node when the next
    // route mounts.
    act(() => {
      wrapperA.props.ref(null);
    });
    act(() => {
      wrapperB.props.ref(slot);
    });

    // Only B's tree is present; A's tree was unmounted.
    expect(slot.textContent).toBe('route-B');
    expect(slot.querySelectorAll('p')).toHaveLength(1);
  });

  test('repeat ref calls with the same DOM node do not re-mount', () => {
    // StrictMode double-invoke — ref fires multiple times with the
    // same node. The implementation should treat the redundant calls
    // as no-ops; the DOM should still have exactly one rendered tree
    // and React shouldn't warn about double-mounting.
    const wrapper = makeWrapperElement(<p>once</p>) as {
      props: { ref: (el: HTMLElement | null) => void };
    };
    const slot = document.createElement('div');
    document.body.appendChild(slot);

    act(() => {
      wrapper.props.ref(slot);
      wrapper.props.ref(slot);
      wrapper.props.ref(slot);
    });

    expect(slot.querySelectorAll('p')).toHaveLength(1);
    expect(slot.textContent).toBe('once');
  });

  test('ref(null) unmounts the host React tree', () => {
    const wrapper = makeWrapperElement(<p data-testid="x">value</p>) as {
      props: { ref: (el: HTMLElement | null) => void };
    };
    const slot = document.createElement('div');
    document.body.appendChild(slot);
    act(() => {
      wrapper.props.ref(slot);
    });
    expect(slot.querySelector('p')).not.toBeNull();

    act(() => {
      wrapper.props.ref(null);
    });
    expect(slot.querySelector('p')).toBeNull();
  });
});
