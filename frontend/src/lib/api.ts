import axios from 'axios';

const baseURL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

export const api = axios.create({
  baseURL,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
});

// Routes where a 401 is expected (e.g. the initial /me probe before login)
// — for everything else, kick the user back to /login.
const PUBLIC_401_PATHS = ['/users/me', '/auth/jwt/login'];

api.interceptors.response.use(
  (resp) => resp,
  (err) => {
    const status = err?.response?.status;
    const url: string | undefined = err?.config?.url;
    const isPublic = url && PUBLIC_401_PATHS.some((p) => url.includes(p));
    if (status === 401 && !isPublic && typeof window !== 'undefined') {
      const path = window.location.pathname;
      if (path !== '/login' && !path.startsWith('/accept-invite')) {
        window.location.replace(`/login?from=${encodeURIComponent(path)}`);
      }
    }
    // 403 with {"code": "totp_required"} — the password half of the
    // two-phase login is done but TOTP isn't. Route to /2fa which
    // picks between setup and challenge based on server state.
    if (
      status === 403 &&
      err?.response?.data?.detail?.code === 'totp_required' &&
      typeof window !== 'undefined'
    ) {
      const path = window.location.pathname;
      if (!path.startsWith('/2fa')) {
        window.location.replace(`/2fa?from=${encodeURIComponent(path)}`);
      }
    }
    return Promise.reject(err);
  },
);
