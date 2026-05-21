// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Sanitise an in-app post-login redirect target.
 *
 * Both `LoginPage` and `TwoFactorPage` read a `from` parameter to
 * decide where to navigate after a successful authentication step.
 * The value may come from React Router state (set by `<RequireAuth>`)
 * or from the URL's `?from=` query (set by `api.ts`'s 401 hard-
 * redirect and by server-side routes that 302 unauth visitors to
 * `/login` — e.g. atrium-pa's `/oauth/authorize`).
 *
 * Without sanitisation, `?from=https://evil.example` (or
 * `//evil.example`) lets a phishing email bounce the user post-login
 * to an attacker-controlled origin where their fresh session cookie
 * would NOT travel — but where the attacker can mimic the SPA shell
 * and harvest credentials.
 *
 * Accepts: `/`, `/foo`, `/foo?bar=baz`, `/foo#frag` (same-origin
 * site-absolute paths).
 *
 * Rejects (returns `null`): empty / null, anything not starting with
 * `/`, anything starting with `//` (protocol-relative), anything with
 * a scheme like `javascript:`. The caller falls through to its own
 * default ('/').
 */
export function sanitizeRedirect(
  value: string | null | undefined,
): string | null {
  if (!value) return null;
  if (!value.startsWith('/')) return null;
  if (value.startsWith('//')) return null;
  return value;
}

/**
 * Does this same-origin path point at a server route rather than an
 * SPA route?
 *
 * React Router's `navigate(...)` only resolves against the `<Routes>`
 * tree — any target that isn't a registered SPA route falls through
 * to the catch-all `<Navigate to="/" />` and the server never sees
 * the request. For host-registered server endpoints (atrium-pa's
 * `/oauth/authorize`, `/api/*` JSON routes that 302'd a browser
 * here, RFC `/.well-known/*` endpoints) the post-login redirect has
 * to be a full-page navigation via `window.location` so the browser
 * actually hits the server.
 *
 * Caller must pass a value already cleared by `sanitizeRedirect`
 * (starts with a single `/`, no scheme, no `//`).
 */
export function isServerRoute(value: string): boolean {
  return (
    value.startsWith('/api/') ||
    value === '/api' ||
    value.startsWith('/oauth/') ||
    value === '/oauth' ||
    value.startsWith('/.well-known/') ||
    value === '/.well-known'
  );
}
