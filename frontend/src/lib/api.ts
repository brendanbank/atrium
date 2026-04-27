import axios from 'axios';

const baseURL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

export const api = axios.create({
  baseURL,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
});

// Routes where a 401 is expected and the page handles it locally —
// don't kick the user back to /login. Examples: the initial /me
// probe before login, the password-reconfirm on self-delete (a
// 401 means "wrong password", which the modal renders inline).
const PUBLIC_401_PATHS = [
  '/users/me',
  '/users/me/delete',
  '/auth/jwt/login',
];

api.interceptors.response.use(
  (resp) => resp,
  (err) => {
    const status = err?.response?.status;
    const url: string | undefined = err?.config?.url;
    const isPublic = url && PUBLIC_401_PATHS.some((p) => url.includes(p));
    if (status === 401 && !isPublic && typeof window !== 'undefined') {
      const path = window.location.pathname;
      // While the document is still loading, an early 401 from a
      // component that mounted before RequireAuth's /me probe resolved
      // can race with the in-flight navigation: window.location.replace
      // aborts the load (Playwright sees ERR_ABORTED). Skip the hard
      // redirect — RequireAuth will SPA-Navigate to /login once the
      // probe lands.
      const isInitialLoad = document.readyState !== 'complete';
      if (
        !isInitialLoad &&
        path !== '/login' &&
        !path.startsWith('/accept-invite') &&
        !path.startsWith('/register') &&
        !path.startsWith('/verify-email')
      ) {
        window.location.replace(`/login?from=${encodeURIComponent(path)}`);
      }
    }
    // 403 with {"code": "totp_required"} — the password half of the
    // two-phase login is done but TOTP isn't. Route to /2fa which
    // picks between setup and challenge based on server state.
    //
    // The sibling code "2fa_enrollment_required" surfaces when the
    // user holds a role listed in auth.require_2fa_for_roles but has
    // no confirmed 2FA factor. Same redirect — /2fa already shows the
    // setup picker for unenrolled users — but a distinct code lets a
    // future UI variant render a different banner.
    const detailCode = err?.response?.data?.detail?.code;
    if (
      status === 403 &&
      (detailCode === 'totp_required' ||
        detailCode === '2fa_enrollment_required') &&
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
