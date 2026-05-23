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
 * a scheme like `javascript:`, anything whose resolved origin differs
 * from the document origin. The caller falls through to its own
 * default ('/').
 *
 * The two-stage check (string prefix → URL constructor → origin
 * equality → reconstruction from `pathname + search + hash`) is the
 * shape CodeQL's `js/client-side-unvalidated-url-redirection` query
 * recognises as a sanitizer. A simpler `startsWith` check passes the
 * same tests but the analyzer flags it as an unsanitised flow.
 */
export function sanitizeRedirect(
  value: string | null | undefined,
): string | null {
  if (!value) return null;
  if (!value.startsWith('/')) return null;
  if (value.startsWith('//')) return null;

  // Fall back to a synthetic base for non-browser callers (vitest's
  // jsdom env does set ``window.location``, but server-rendered or
  // ssr-probe contexts may not). The base is only used to resolve
  // the parsed URL — its scheme/host never escape this function.
  const base =
    typeof window !== 'undefined' && window.location?.origin
      ? window.location.origin
      : 'http://localhost';

  let url: URL;
  try {
    url = new URL(value, base);
  } catch {
    return null;
  }

  // Origin equality is the gate the analyzer keys on. Any scheme,
  // host, or port drift fails closed.
  if (url.origin !== base) return null;

  // Reconstruct from validated components rather than returning the
  // input verbatim — this is the "rebuild from trusted parts"
  // sanitizer pattern.
  return `${url.pathname}${url.search}${url.hash}`;
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
