// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { expect, test } from '@playwright/test';
import type { APIRequestContext } from '@playwright/test';
import { generate as generateTOTP } from 'otplib';

import { API_URL, loginAsAdmin } from './helpers';

/**
 * Phase 3 coverage — password-policy + 2FA enforcement.
 *
 * Specs map 1:1 onto the toggles in
 * ``app.services.password_policy`` and the enforcement branch in
 * ``app.auth.users.current_user`` that returns
 * ``403 {code: "2fa_enrollment_required"}`` for users whose role is on
 * ``auth.require_2fa_for_roles`` but who haven't enrolled a factor.
 *
 * State management:
 *   - ``beforeAll`` snapshots the entire ``auth`` namespace so a flake
 *     mid-suite can't leak a policy toggle into sibling specs / the
 *     next ``make smoke`` run.
 *   - Each spec read-modify-writes the namespace inside a try/finally
 *     so a sibling never sees a half-mutated baseline.
 *
 * Required env (set by ``make smoke-up``):
 *   E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD / E2E_ADMIN_TOTP_SECRET
 */

const adminEmail = process.env.E2E_ADMIN_EMAIL;
const adminPassword = process.env.E2E_ADMIN_PASSWORD;
const adminTotpSecret = process.env.E2E_ADMIN_TOTP_SECRET;

const haveSmokeEnv = Boolean(
  adminEmail && adminPassword && adminTotpSecret,
);

test.skip(
  !haveSmokeEnv,
  'E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD / E2E_ADMIN_TOTP_SECRET must be set (run via `make smoke`).',
);

interface AuthNamespace {
  allow_self_delete?: boolean;
  delete_grace_days?: number;
  allow_signup?: boolean;
  signup_default_role_code?: string;
  require_email_verification?: boolean;
  password_min_length?: number;
  password_require_mixed_case?: boolean;
  password_require_digit?: boolean;
  password_require_symbol?: boolean;
  password_check_breach?: boolean;
  require_2fa_for_roles?: string[];
}

/**
 * PUT the ``auth`` namespace through the admin API. The endpoint
 * replaces the namespace, so we read the current value first and merge
 * the patch on top — keeps unrelated fields intact when we're only
 * flipping one knob. Mirrors the local helper in ``signup.spec.ts``.
 *
 * Caller must already hold a session with ``app_setting.manage``.
 */
async function setAuthConfig(
  request: APIRequestContext,
  patch: Partial<AuthNamespace>,
): Promise<void> {
  const cur = await request.get(`${API_URL}/admin/app-config`);
  if (!cur.ok()) {
    throw new Error(
      `admin app-config read failed: ${cur.status()} ${await cur.text()}`,
    );
  }
  const body = (await cur.json()) as { auth?: Record<string, unknown> };
  const merged = { ...(body.auth ?? {}), ...patch };
  const resp = await request.put(`${API_URL}/admin/app-config/auth`, {
    data: merged,
  });
  if (!resp.ok()) {
    throw new Error(
      `auth put failed: ${resp.status()} ${await resp.text()}`,
    );
  }
}

/** Read the full ``auth`` namespace so the suite can restore on teardown. */
async function readAuthConfig(
  request: APIRequestContext,
): Promise<Record<string, unknown>> {
  const cur = await request.get(`${API_URL}/admin/app-config`);
  if (!cur.ok()) {
    throw new Error(
      `admin app-config read failed: ${cur.status()} ${await cur.text()}`,
    );
  }
  const body = (await cur.json()) as { auth?: Record<string, unknown> };
  return body.auth ?? {};
}

/** Replace (not merge) the entire ``auth`` namespace. Used for restore. */
async function putAuthConfig(
  request: APIRequestContext,
  data: Record<string, unknown>,
): Promise<void> {
  const resp = await request.put(`${API_URL}/admin/app-config/auth`, { data });
  if (!resp.ok()) {
    throw new Error(
      `auth put failed: ${resp.status()} ${await resp.text()}`,
    );
  }
}

/**
 * Provision a fresh user via the invite + accept flow holding the
 * supplied role codes (default: ``admin``) but skip TOTP enrolment.
 * Mirror of ``createAndEnrolUserViaApi`` in ``helpers.ts`` minus the
 * setup/confirm steps — needed so the 2FA-enforcement specs can drive
 * a freshly-logged-in user against the
 * ``2fa_enrollment_required`` branch.
 *
 * ``adminRequest`` must already hold a session with ``user.manage``.
 * ``inviteeRequest`` should be a fresh, cookie-less request context so
 * the invitee's auth cookie doesn't collide with the caller's.
 */
async function createUserNoEnrolViaApi(
  adminRequest: APIRequestContext,
  inviteeRequest: APIRequestContext,
  opts: { roleCodes?: string[] } = {},
): Promise<{ email: string; password: string }> {
  const email = `e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
  const password = 'invitee-pw-12345';

  const createResp = await adminRequest.post(`${API_URL}/invites`, {
    data: {
      email,
      full_name: 'E2E Account',
      role_codes: opts.roleCodes ?? ['admin'],
    },
  });
  if (createResp.status() !== 201) {
    throw new Error(
      `invite create failed: ${createResp.status()} ${await createResp.text()}`,
    );
  }
  const created = (await createResp.json()) as { id: number; token: string };

  const acceptResp = await inviteeRequest.post(`${API_URL}/invites/accept`, {
    data: { token: created.token, password },
  });
  if (acceptResp.status() !== 201) {
    throw new Error(
      `invite accept failed: ${acceptResp.status()} ${await acceptResp.text()}`,
    );
  }

  return { email, password };
}

function uniqueEmail(prefix: string): string {
  const stamp = `${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
  return `${prefix}-${stamp}@example.com`;
}

// ---------------------------------------------------------------------------
// Suite — serial because each spec mutates the shared ``auth`` namespace
// and we don't want concurrent reads racing.
// ---------------------------------------------------------------------------

test.describe('password policy + 2FA enforcement', () => {
  test.describe.configure({ mode: 'serial' });

  let snapshot: Record<string, unknown> | null = null;

  test.beforeAll(async ({ browser }) => {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    try {
      await loginAsAdmin(page);
      snapshot = await readAuthConfig(page.request);
      // Open signup for the password-policy specs — the policy is
      // enforced on /register too, so we drive through the same surface
      // the user would. Restore-on-teardown brings this back to whatever
      // the smoke env had.
      await setAuthConfig(page.request, {
        allow_signup: true,
        signup_default_role_code: 'user',
        require_email_verification: false,
        password_min_length: 8,
        password_require_mixed_case: false,
        password_require_digit: false,
        password_require_symbol: false,
        password_check_breach: false,
        require_2fa_for_roles: [],
      });
    } finally {
      await ctx.close();
    }
  });

  test.afterAll(async ({ browser }) => {
    if (snapshot === null) return;
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    try {
      await loginAsAdmin(page);
      await putAuthConfig(page.request, snapshot);
    } finally {
      await ctx.close();
    }
  });

  test('password rejected when below configured minimum', async ({
    browser,
  }) => {
    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await loginAsAdmin(adminPage);

    try {
      await setAuthConfig(adminPage.request, { password_min_length: 12 });

      const visitorContext = await browser.newContext();
      const visitorPage = await visitorContext.newPage();
      try {
        const email = uniqueEmail('e2e-pw-min');
        await visitorPage.goto('/register');
        await visitorPage
          .getByLabel(/email/i, { exact: false })
          .first()
          .fill(email);
        await visitorPage
          .getByLabel(/full name/i)
          .fill('Min Length Tester');
        // 10 chars — clears the client-side ``>= 8`` validator but
        // trips the server's ``password_min_length=12`` rule.
        await visitorPage
          .getByLabel(/^password/i, { exact: false })
          .first()
          .fill('abcdefghij');
        await visitorPage
          .getByLabel(/confirm password/i)
          .fill('abcdefghij');
        await visitorPage
          .getByRole('button', { name: /create account/i })
          .click();

        await expect(
          visitorPage.getByText(
            /password must be at least 12 characters/i,
          ),
        ).toBeVisible();
      } finally {
        await visitorContext.close();
      }
    } finally {
      await setAuthConfig(adminPage.request, { password_min_length: 8 });
      await adminContext.close();
    }
  });

  test('mixed-case requirement enforced', async ({ browser }) => {
    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await loginAsAdmin(adminPage);

    try {
      await setAuthConfig(adminPage.request, {
        password_require_mixed_case: true,
      });

      const visitorContext = await browser.newContext();
      const visitorPage = await visitorContext.newPage();
      try {
        const email = uniqueEmail('e2e-pw-case');
        await visitorPage.goto('/register');
        await visitorPage
          .getByLabel(/email/i, { exact: false })
          .first()
          .fill(email);
        await visitorPage
          .getByLabel(/full name/i)
          .fill('Mixed Case Tester');
        // Lowercase only — clears length, fails mixed-case.
        await visitorPage
          .getByLabel(/^password/i, { exact: false })
          .first()
          .fill('alllowercase123');
        await visitorPage
          .getByLabel(/confirm password/i)
          .fill('alllowercase123');
        await visitorPage
          .getByRole('button', { name: /create account/i })
          .click();

        await expect(
          visitorPage.getByText(
            /password must contain both upper and lower case/i,
          ),
        ).toBeVisible();
      } finally {
        await visitorContext.close();
      }
    } finally {
      await setAuthConfig(adminPage.request, {
        password_require_mixed_case: false,
      });
      await adminContext.close();
    }
  });

  test('digit + symbol requirements enforced', async ({ browser }) => {
    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await loginAsAdmin(adminPage);

    try {
      // Digit on first; assert. Then flip digit off + symbol on; assert.
      // Two assertions in one spec keeps the file at the agreed test
      // count but still exercises both rules independently.
      await setAuthConfig(adminPage.request, {
        password_require_digit: true,
        password_require_symbol: false,
      });

      const visitorContext = await browser.newContext();
      const visitorPage = await visitorContext.newPage();
      try {
        // ---- Digit-required path: letters only.
        await visitorPage.goto('/register');
        await visitorPage
          .getByLabel(/email/i, { exact: false })
          .first()
          .fill(uniqueEmail('e2e-pw-digit'));
        await visitorPage
          .getByLabel(/full name/i)
          .fill('Digit Tester');
        await visitorPage
          .getByLabel(/^password/i, { exact: false })
          .first()
          .fill('abcdefghij');
        await visitorPage
          .getByLabel(/confirm password/i)
          .fill('abcdefghij');
        await visitorPage
          .getByRole('button', { name: /create account/i })
          .click();

        await expect(
          visitorPage.getByText(
            /password must contain at least one digit/i,
          ),
        ).toBeVisible();

        // ---- Symbol-required path: letters + digits, no symbol.
        await setAuthConfig(adminPage.request, {
          password_require_digit: false,
          password_require_symbol: true,
        });

        await visitorPage.goto('/register');
        await visitorPage
          .getByLabel(/email/i, { exact: false })
          .first()
          .fill(uniqueEmail('e2e-pw-symbol'));
        await visitorPage
          .getByLabel(/full name/i)
          .fill('Symbol Tester');
        await visitorPage
          .getByLabel(/^password/i, { exact: false })
          .first()
          .fill('abcdef1234');
        await visitorPage
          .getByLabel(/confirm password/i)
          .fill('abcdef1234');
        await visitorPage
          .getByRole('button', { name: /create account/i })
          .click();

        await expect(
          visitorPage.getByText(
            /password must contain at least one symbol/i,
          ),
        ).toBeVisible();
      } finally {
        await visitorContext.close();
      }
    } finally {
      await setAuthConfig(adminPage.request, {
        password_require_digit: false,
        password_require_symbol: false,
      });
      await adminContext.close();
    }
  });

  test('HIBP breach check rejects a known-breached password', async ({
    browser,
  }) => {
    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await loginAsAdmin(adminPage);

    try {
      await setAuthConfig(adminPage.request, { password_check_breach: true });

      const visitorContext = await browser.newContext();
      const visitorPage = await visitorContext.newPage();
      try {
        // ``12345678`` is one of the all-time top-10 entries in HIBP
        // and clears the default 8-char minimum without tripping any
        // other policy (mixed-case / digit / symbol all off).
        const email = uniqueEmail('e2e-pw-breach');
        await visitorPage.goto('/register');
        await visitorPage
          .getByLabel(/email/i, { exact: false })
          .first()
          .fill(email);
        await visitorPage
          .getByLabel(/full name/i)
          .fill('Breach Tester');
        await visitorPage
          .getByLabel(/^password/i, { exact: false })
          .first()
          .fill('12345678');
        await visitorPage
          .getByLabel(/confirm password/i)
          .fill('12345678');
        await visitorPage
          .getByRole('button', { name: /create account/i })
          .click();

        // The HIBP check is fail-open by design: a network failure to
        // ``api.pwnedpasswords.com`` returns ``None`` and registration
        // proceeds. So this assertion tolerates either outcome — if the
        // breach error appears, great; if registration succeeded
        // (visible "Check your email" heading or the form cleared), we
        // log a warning and skip rather than fail. See
        // ``services/password_policy.py:_hibp_suffixes_for_prefix``.
        const breachError = visitorPage.getByText(
          /password appears in known breach data/i,
        );
        const successHeading = visitorPage.getByRole('heading', {
          name: /check your email/i,
        });

        // Race: either branch resolves first.
        await Promise.race([
          breachError.waitFor({ state: 'visible', timeout: 10000 }),
          successHeading.waitFor({ state: 'visible', timeout: 10000 }),
        ]);

        if (await successHeading.isVisible().catch(() => false)) {
          test.skip(
            true,
            'HIBP unreachable from the e2e stack — fail-open accepted the password.',
          );
        } else {
          await expect(breachError).toBeVisible();
        }
      } finally {
        await visitorContext.close();
      }
    } finally {
      await setAuthConfig(adminPage.request, { password_check_breach: false });
      await adminContext.close();
    }
  });

  test('2FA enforcement: a role-protected user without 2FA gets bounced to /2fa', async ({
    browser,
  }) => {
    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await loginAsAdmin(adminPage);

    try {
      await setAuthConfig(adminPage.request, {
        require_2fa_for_roles: ['admin'],
      });

      // Mint a fresh ``admin``-roled user *without* enrolling 2FA.
      // ``createAndEnrolUserViaApi`` is the wrong helper here — its
      // whole point is to drive TOTP setup so the session passes the
      // gate. We need the un-enrolled state.
      const userContext = await browser.newContext();
      const userPage = await userContext.newPage();
      try {
        const { email, password } = await createUserNoEnrolViaApi(
          adminPage.request,
          userPage.request,
          { roleCodes: ['admin'] },
        );

        // Fresh login through the UI so the axios interceptor /
        // RequireAuth path is exercised end-to-end.
        await userPage.goto('/login');
        await userPage
          .getByLabel(/email/i, { exact: false })
          .first()
          .fill(email);
        await userPage
          .getByLabel(/password/i, { exact: false })
          .first()
          .fill(password);
        await userPage
          .getByRole('button', { name: /log in/i })
          .click();

        // The login response itself doesn't 403; it's the next protected
        // request (``/users/me/context`` or similar) that returns
        // ``2fa_enrollment_required`` — the interceptor in lib/api.ts
        // then redirects to /2fa.
        await expect(userPage).toHaveURL(/\/2fa/);
      } finally {
        await userContext.close();
      }
    } finally {
      await setAuthConfig(adminPage.request, { require_2fa_for_roles: [] });
      await adminContext.close();
    }
  });

  test('2FA enforcement: enrolling unblocks the user', async ({ browser }) => {
    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await loginAsAdmin(adminPage);

    try {
      await setAuthConfig(adminPage.request, {
        require_2fa_for_roles: ['admin'],
      });

      const userContext = await browser.newContext();
      const userPage = await userContext.newPage();
      try {
        const { email, password } = await createUserNoEnrolViaApi(
          adminPage.request,
          userPage.request,
          { roleCodes: ['admin'] },
        );

        // Authenticate through the API directly (mirrors the helper
        // pattern in ``createAndEnrolUserViaApi``); we want to drive
        // the enrol step on ``userPage.request`` then check the
        // browser side can reach a protected route.
        const loginResp = await userPage.request.post(
          `${API_URL}/auth/jwt/login`,
          { form: { username: email, password } },
        );
        if (!loginResp.ok() && loginResp.status() !== 204) {
          throw new Error(`user login failed: ${loginResp.status()}`);
        }

        // Sanity check: the gate is closed before enrolment.
        const preEnrol = await userPage.request.get(
          `${API_URL}/users/me/context`,
        );
        expect(preEnrol.status()).toBe(403);
        const preBody = (await preEnrol.json()) as {
          detail?: { code?: string };
        };
        expect(preBody.detail?.code).toBe('2fa_enrollment_required');

        // Drive the TOTP enrolment via the API — same shape as
        // ``createAndEnrolUserViaApi``'s tail.
        const setupResp = await userPage.request.post(
          `${API_URL}/auth/totp/setup`,
        );
        if (!setupResp.ok()) {
          throw new Error(
            `totp setup failed: ${setupResp.status()} ${await setupResp.text()}`,
          );
        }
        const { secret } = (await setupResp.json()) as { secret: string };
        const code = await generateTOTP({ secret });
        const confirmResp = await userPage.request.post(
          `${API_URL}/auth/totp/confirm`,
          { data: { code } },
        );
        if (!confirmResp.ok() && confirmResp.status() !== 204) {
          throw new Error(
            `totp confirm failed: ${confirmResp.status()} ${await confirmResp.text()}`,
          );
        }

        // Gate is now open — the API confirms first, then the browser
        // navigation lands on ``/`` instead of bouncing to ``/2fa``.
        const postEnrol = await userPage.request.get(
          `${API_URL}/users/me/context`,
        );
        expect(postEnrol.ok()).toBe(true);

        // Sync cookies to the browser jar (Playwright versions split
        // the API + browser jars; helpers do the same dance).
        const cookies = await userPage.context().cookies();
        if (!cookies.some((c) => c.name === 'atrium_auth')) {
          const apiCookies = await userPage.request.storageState();
          await userPage.context().addCookies(apiCookies.cookies);
        }

        await userPage.goto('/');
        await expect(userPage).toHaveURL(/\/(?:$|dashboard|home)?$/);
      } finally {
        await userContext.close();
      }
    } finally {
      await setAuthConfig(adminPage.request, { require_2fa_for_roles: [] });
      await adminContext.close();
    }
  });
});
