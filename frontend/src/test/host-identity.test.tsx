// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Vitest coverage for the identity bridge.
 *
 * Pins down the contract host bundles rely on: every change to the
 * signed-in user identity fires one ``atrium:userchange`` CustomEvent
 * on ``window`` carrying ``{previous, current, nonce}``. The first
 * observation is a baseline (no dispatch); subsequent transitions —
 * login, logout, impersonation start/stop, same-tab re-login — fire.
 * See atrium #87.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { cleanup, render, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import {
  ATRIUM_USERCHANGE_EVENT,
  IdentityBridge,
  __resetIdentityNonceForTests,
  dispatchUserChange,
  type AtriumUserChangeDetail,
} from '@/host/identity';
import { ME_QUERY_KEY } from '@/hooks/useAuth';
import type { CurrentUser } from '@/lib/auth';

type Capture = AtriumUserChangeDetail[];

function captureEvents(): { events: Capture; off: () => void } {
  const events: Capture = [];
  const handler = (e: Event) => {
    const detail = (e as CustomEvent<AtriumUserChangeDetail>).detail;
    events.push({ ...detail });
  };
  window.addEventListener(ATRIUM_USERCHANGE_EVENT, handler);
  return {
    events,
    off: () => window.removeEventListener(ATRIUM_USERCHANGE_EVENT, handler),
  };
}

function makeUser(id: number): CurrentUser {
  return {
    id,
    email: `user${id}@example.com`,
    full_name: `User ${id}`,
    is_active: true,
    is_verified: true,
    is_superuser: false,
    phone: null,
    preferred_language: 'en',
    roles: [],
    permissions: [],
    impersonating_from: null,
  } as CurrentUser;
}

function makeClient(initial: CurrentUser | null): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  qc.setQueryData(ME_QUERY_KEY, initial);
  return qc;
}

function renderBridge(qc: QueryClient) {
  return render(
    <QueryClientProvider client={qc}>
      <IdentityBridge />
    </QueryClientProvider>,
  );
}

describe('IdentityBridge', () => {
  beforeEach(() => {
    cleanup();
    __resetIdentityNonceForTests();
  });

  it('does not dispatch on first observation (baseline adoption)', () => {
    // Page reload of a signed-in tab is "user X is signed in", not
    // "user X just signed in" — the first known identity is the
    // baseline, no event.
    const cap = captureEvents();
    try {
      const qc = makeClient(makeUser(7));
      renderBridge(qc);
      expect(cap.events).toHaveLength(0);
    } finally {
      cap.off();
    }
  });

  it('does not dispatch on first observation when signed out', () => {
    const cap = captureEvents();
    try {
      const qc = makeClient(null);
      renderBridge(qc);
      expect(cap.events).toHaveLength(0);
    } finally {
      cap.off();
    }
  });

  it('fires when null → user (login from a fresh tab)', async () => {
    const cap = captureEvents();
    try {
      const qc = makeClient(null);
      renderBridge(qc);
      cap.events.length = 0;

      qc.setQueryData(ME_QUERY_KEY, makeUser(7));

      await waitFor(() => expect(cap.events).toHaveLength(1));
      expect(cap.events[0]).toEqual({
        previous: null,
        current: 7,
        nonce: 1,
      });
    } finally {
      cap.off();
    }
  });

  it('fires when user → null (logout)', async () => {
    const cap = captureEvents();
    try {
      const qc = makeClient(makeUser(7));
      renderBridge(qc);
      cap.events.length = 0;

      qc.setQueryData(ME_QUERY_KEY, null);

      await waitFor(() => expect(cap.events).toHaveLength(1));
      expect(cap.events[0]).toEqual({
        previous: 7,
        current: null,
        nonce: 1,
      });
    } finally {
      cap.off();
    }
  });

  it('fires when user A → user B (same-tab re-login or impersonation)', async () => {
    const cap = captureEvents();
    try {
      const qc = makeClient(makeUser(7));
      renderBridge(qc);
      cap.events.length = 0;

      qc.setQueryData(ME_QUERY_KEY, makeUser(11));

      await waitFor(() => expect(cap.events).toHaveLength(1));
      expect(cap.events[0]).toEqual({
        previous: 7,
        current: 11,
        nonce: 1,
      });
    } finally {
      cap.off();
    }
  });

  it('does not fire when the same user re-renders with an unchanged id', async () => {
    // Refetches that return the same user (e.g. a permissions refresh)
    // produce a new object reference but the same id — no transition.
    const cap = captureEvents();
    try {
      const qc = makeClient(makeUser(7));
      renderBridge(qc);
      cap.events.length = 0;

      qc.setQueryData(ME_QUERY_KEY, makeUser(7));
      // Give the QueryObserver a tick to fire and any latent dispatch
      // a chance to land. After that the events buffer must still be
      // empty — same id, no transition.
      await new Promise((resolve) => setTimeout(resolve, 20));

      expect(cap.events).toHaveLength(0);
    } finally {
      cap.off();
    }
  });

  it('attaches a monotonically-increasing nonce to every event', async () => {
    const cap = captureEvents();
    try {
      // Direct dispatches simulate the bridge firing on rapid
      // transitions; the nonce must strictly increase so a host effect
      // keyed on it re-runs even when {previous, current} repeats.
      dispatchUserChange({ previous: null, current: 7 });
      dispatchUserChange({ previous: 7, current: null });
      dispatchUserChange({ previous: null, current: 7 });

      const nonces = cap.events.map((e) => e.nonce);
      expect(nonces.length).toBe(3);
      expect(nonces[1]).toBeGreaterThan(nonces[0]);
      expect(nonces[2]).toBeGreaterThan(nonces[1]);
    } finally {
      cap.off();
    }
  });

  it('handles a sequence: login, impersonate, stop impersonate, logout', async () => {
    const cap = captureEvents();
    try {
      const qc = makeClient(null);
      renderBridge(qc);
      cap.events.length = 0;

      // Login as actor (id 1).
      qc.setQueryData(ME_QUERY_KEY, makeUser(1));
      await waitFor(() => expect(cap.events).toHaveLength(1));
      // Start impersonating target (id 42) — `/users/me/context` now
      // returns the target's id.
      qc.setQueryData(ME_QUERY_KEY, makeUser(42));
      await waitFor(() => expect(cap.events).toHaveLength(2));
      // Stop impersonating — back to the actor.
      qc.setQueryData(ME_QUERY_KEY, makeUser(1));
      await waitFor(() => expect(cap.events).toHaveLength(3));
      // Logout.
      qc.setQueryData(ME_QUERY_KEY, null);
      await waitFor(() => expect(cap.events).toHaveLength(4));

      expect(cap.events.map((e) => [e.previous, e.current])).toEqual([
        [null, 1],
        [1, 42],
        [42, 1],
        [1, null],
      ]);
    } finally {
      cap.off();
    }
  });
});
