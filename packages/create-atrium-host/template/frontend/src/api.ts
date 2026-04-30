/** Plain fetch — no axios. `credentials: 'include'` carries atrium's
 *  auth cookie so authenticated routes work the same as from atrium's
 *  own SPA. Build with `VITE_API_BASE_URL="/api"` (the default in the
 *  Dockerfile) so the bundle calls atrium's API namespace — every
 *  JSON route lives under /api/... so the SPA owns un-prefixed URL
 *  space (atrium issue #89).
 */
const apiBase =
  (import.meta as { env?: { VITE_API_BASE_URL?: string } }).env?.VITE_API_BASE_URL ??
  '/api';

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`api ${res.status}: ${body}`);
  }
  return (await res.json()) as T;
}

export interface __BRAND_PASCAL__State {
  message: string;
  counter: number;
}

export async function get__BRAND_PASCAL__State(): Promise<__BRAND_PASCAL__State> {
  const res = await fetch(`${apiBase}/__HOST_PKG__/state`, {
    credentials: 'include',
    headers: { Accept: 'application/json' },
  });
  return jsonOrThrow<__BRAND_PASCAL__State>(res);
}

export async function bump__BRAND_PASCAL__(): Promise<__BRAND_PASCAL__State> {
  const res = await fetch(`${apiBase}/__HOST_PKG__/bump`, {
    method: 'POST',
    credentials: 'include',
    headers: { Accept: 'application/json' },
  });
  return jsonOrThrow<__BRAND_PASCAL__State>(res);
}
