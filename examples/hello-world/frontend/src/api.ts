// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/** Thin fetch wrapper for the host's /hello/* endpoints + the
 *  atrium /users/me/context probe used to gate the toggle.
 *
 * We don't import atrium's axios instance — this bundle is loaded at
 * runtime and atrium's modules aren't reachable as imports. The
 * cookie-based session is shared on the same origin so
 * ``credentials: 'include'`` is enough. */
export interface HelloState {
  message: string;
  counter: number;
  enabled: boolean;
}

export interface MeContext {
  id: number;
  email: string;
  full_name: string;
  roles: string[];
  permissions: string[];
}

const apiBase = (import.meta as { env?: { VITE_API_BASE_URL?: string } }).env
  ?.VITE_API_BASE_URL ?? '/api';

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`hello api ${res.status}: ${body}`);
  }
  return (await res.json()) as T;
}

export async function getHelloState(): Promise<HelloState> {
  const res = await fetch(`${apiBase}/hello/state`, {
    credentials: 'include',
    headers: { Accept: 'application/json' },
  });
  return jsonOrThrow<HelloState>(res);
}

export async function postHelloToggle(enabled: boolean): Promise<HelloState> {
  const res = await fetch(`${apiBase}/hello/toggle`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ enabled }),
  });
  return jsonOrThrow<HelloState>(res);
}

export async function getMeContext(): Promise<MeContext | null> {
  const res = await fetch(`${apiBase}/users/me/context`, {
    credentials: 'include',
    headers: { Accept: 'application/json' },
  });
  if (res.status === 401 || res.status === 403) return null;
  return jsonOrThrow<MeContext>(res);
}
