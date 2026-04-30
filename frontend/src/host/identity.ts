// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Atrium identity bridge for host bundles.
 *
 * Host bundles run their own TanStack QueryClient — atrium and the
 * host don't share a cache, by design (a shared client would lose
 * host queries the user still wants the next time atrium calls
 * `qc.clear()` on logout). The downside is that when atrium swaps
 * sessions — log out + log in as another user, or super_admin
 * impersonates a target — the host has no signal to wipe its own
 * cache, so user A's host data renders for user B until staleness
 * forces a refetch.
 *
 * To close the gap atrium dispatches an ``atrium:userchange``
 * CustomEvent on ``window`` whenever the signed-in user identity
 * changes. The detail payload is ``{previous, current, nonce}`` —
 * ``previous`` and ``current`` are the user ids before and after
 * (``null`` when signed out / not yet signed in), and ``nonce`` is a
 * monotonic counter atrium increments on every dispatch.
 *
 * The event covers every transition that changes the runtime user
 * identity:
 *
 *  - successful login (``null`` → user)
 *  - logout (user → ``null``)
 *  - logout-all (user → ``null``)
 *  - super_admin starts impersonating (actor → target)
 *  - super_admin stops impersonating (target → actor)
 *  - same-tab re-login as a different user (user A → user B)
 *
 * It does NOT fire on the very first identity observation after a
 * page load — by definition the user has not changed; they were
 * already that user when the tab opened. Hosts that need the initial
 * identity should read it from ``useUserContext()`` (or its
 * equivalent) — that's the canonical source for "who is signed in
 * right now", whereas this event is strictly the signal "the answer
 * just changed".
 *
 * Hosts subscribe with a plain ``addEventListener`` (no React
 * coupling, fires even when no host subtree is mounted) or via the
 * ``useAtriumUser()`` hook in
 * ``@brendanbank/atrium-host-bundle-utils/react`` (which wraps the
 * event in ``useSyncExternalStore``).
 */
import { useEffect, useRef } from 'react';

import { useMe } from '@/hooks/useAuth';

export type AtriumUserChangeDetail = {
  /** User id before the change, or ``null`` when transitioning out
   *  of the signed-out state. */
  previous: number | null;
  /** User id after the change, or ``null`` when the new state is
   *  signed out. */
  current: number | null;
  /** Monotonic counter, incremented atomically by atrium on every
   *  ``atrium:userchange`` dispatch. The value has no semantic
   *  meaning — only that it's strictly greater than the previous
   *  event's nonce. Use it in effect deps when an effect should
   *  re-run on every transition. */
  nonce: number;
};

export const ATRIUM_USERCHANGE_EVENT = 'atrium:userchange';

let nextNonce = 0;

/** Fire a single ``atrium:userchange`` event on ``window``.
 *
 *  Callers pass ``{previous, current}``; the helper adds a fresh
 *  monotonic nonce. Exported so non-bridge call sites can force a
 *  dispatch in the rare cases where the underlying ``useMe`` query
 *  hasn't observed the transition yet. */
export function dispatchUserChange(
  detail: Omit<AtriumUserChangeDetail, 'nonce'>,
): void {
  if (typeof window === 'undefined') return;
  const nonce = ++nextNonce;
  window.dispatchEvent(
    new CustomEvent<AtriumUserChangeDetail>(ATRIUM_USERCHANGE_EVENT, {
      detail: { ...detail, nonce },
    }),
  );
}

/** Mounts inside the atrium SPA and re-dispatches every change to the
 *  signed-in user identity as a ``window`` CustomEvent. Renders nothing.
 *
 *  ``useMe()`` is the canonical source — every login / logout /
 *  impersonation flow refetches it (login does ``qc.refetchQueries``,
 *  logout does ``qc.clear``, impersonate does ``qc.invalidateQueries``).
 *  Tracking its ``data?.id`` therefore catches every identity transition
 *  with one subscription, instead of sprinkling ``dispatchUserChange``
 *  through every flow.
 *
 *  The first observed value is treated as a baseline, NOT a transition
 *  (a page reload of an already-signed-in tab is "user X is signed in",
 *  not "user X just signed in"). Subsequent changes always fire. */
export function IdentityBridge(): null {
  // ``undefined`` on the very first render — distinguishes "haven't
  // observed yet" from "observed null (signed out)". A normal
  // ``useState`` initializer would lose that distinction across
  // renders.
  const lastIdRef = useRef<number | null | undefined>(undefined);
  const { data, isPending } = useMe();
  // Read the id off the result. ``null`` is the explicit signed-out
  // state; ``undefined`` means the query hasn't resolved yet (we
  // don't dispatch in that case).
  const currentId: number | null | undefined = isPending
    ? undefined
    : (data?.id ?? null);

  useEffect(() => {
    if (currentId === undefined) return;
    const previous = lastIdRef.current;
    if (previous === undefined) {
      // First observation — adopt as the baseline without dispatching.
      lastIdRef.current = currentId;
      return;
    }
    if (previous === currentId) return;
    lastIdRef.current = currentId;
    dispatchUserChange({ previous, current: currentId });
  }, [currentId]);

  return null;
}

/** Test-only: reset the module-level nonce counter so each test starts
 *  from a known baseline. Production code never calls this. */
export function __resetIdentityNonceForTests(): void {
  nextNonce = 0;
}
