// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { execSync } from 'child_process';

import { expect, test } from '@playwright/test';
import type { APIRequestContext } from '@playwright/test';

import { API_URL, loginAsAdmin } from './helpers';

/**
 * Phase 2 coverage — self-serve signup + email verification.
 *
 * The atrium default is ``auth.allow_signup=false`` so the route 404s
 * and the Login page hides the CTA. These specs flip the toggle on
 * (per-spec, with a finally-clause that puts it back) and drive the
 * full register → email-link → verify → login flow against the e2e
 * stack. The verify URL is fished out of the api container's stdout
 * the same way ``email-otp.spec`` reads the OTP code — no real mailbox
 * is required because the dev/e2e stack uses ``MAIL_BACKEND=console``.
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
  allow_signup: boolean;
  signup_default_role_code: string;
  require_email_verification: boolean;
}

/**
 * PUT the ``auth`` namespace through the admin API. The endpoint
 * replaces the namespace, so we read the current value first and merge
 * the patch on top — keeps unrelated fields (``allow_self_delete``,
 * ``delete_grace_days``) intact when we're only flipping signup knobs.
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

/**
 * Walk the api container's recent stdout for the latest
 * ``[email/console]`` block whose ``To:`` matches ``recipientEmail``
 * and whose ``template=email_verify``, then extract the verify URL
 * from the rendered plain-text body. Returns the *path + query*
 * portion only (e.g. ``/verify-email?token=…``) so the spec can call
 * ``page.goto`` against the Playwright baseURL — the body of the
 * email contains ``settings.app_base_url`` which inside the e2e stack
 * points at the internal nginx, not at ``localhost:5173``.
 */
function readLatestVerifyUrlForEmail(recipientEmail: string): string {
  const compose = process.env.E2E_COMPOSE_FILES ??
    '-f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.e2e.yml';
  const raw = execSync(`docker compose ${compose} logs api --tail 400`, {
    encoding: 'utf-8',
    cwd: '..',
  });

  const blocks = raw.split(/={50,}/);
  for (let i = blocks.length - 1; i >= 0; i--) {
    const block = blocks[i];
    if (
      block.includes('[email/console]') &&
      block.includes(`To:       ${recipientEmail}`) &&
      block.includes('template=email_verify')
    ) {
      // The default ``email_verify`` template renders a single
      // ``<a href="{{ verify_url }}">…</a>`` anchor. After the
      // sender's tag-stripping, the URL is the only ``http(s)://``
      // token in the block that hits ``/verify-email?token=``.
      const match = block.match(
        /https?:\/\/[^\s"'<>]+\/verify-email\?token=[^\s"'<>]+/,
      );
      if (match) {
        // Strip the host so the spec navigates against the Playwright
        // baseURL — the email body's host is the api/proxy origin,
        // not the dev-server origin Playwright is talking to.
        const url = new URL(match[0]);
        return `${url.pathname}${url.search}`;
      }
    }
  }
  throw new Error(
    `no email_verify message for ${recipientEmail} found in api logs`,
  );
}

function uniqueEmail(prefix: string): string {
  const stamp = `${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
  return `${prefix}-${stamp}@example.com`;
}

const VALID_PASSWORD = 'signup-pw-12345';

// ---------------------------------------------------------------------------
// State setup / teardown — flip allow_signup on for the duration of the
// suite, restore the default (off) afterwards. Each individual spec
// that wants a different ``require_email_verification`` value flips it
// in a try/finally so siblings see a consistent baseline.
// ---------------------------------------------------------------------------

test.describe('signup + email verification', () => {
  test.describe.configure({ mode: 'serial' });

  let suiteRequest: APIRequestContext | null = null;

  test.beforeAll(async ({ browser }) => {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    await loginAsAdmin(page);
    suiteRequest = page.request;
    // Open the gate for the suite. Specs that want it closed (the
    // "signup is hidden" case) flip it back inside their own bodies.
    await setAuthConfig(suiteRequest, {
      allow_signup: true,
      signup_default_role_code: 'user',
      require_email_verification: true,
    });
  });

  test.afterAll(async ({ browser }) => {
    // Re-establish an admin session — ``suiteRequest`` may have been
    // closed when its parent context shut down.
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    try {
      await loginAsAdmin(page);
      await setAuthConfig(page.request, {
        allow_signup: false,
        signup_default_role_code: 'user',
        require_email_verification: true,
      });
    } finally {
      await ctx.close();
    }
  });

  test('signup CTA is hidden when auth.allow_signup is false', async ({
    browser,
  }) => {
    // Flip the gate closed for this spec only.
    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await loginAsAdmin(adminPage);

    try {
      await setAuthConfig(adminPage.request, { allow_signup: false });

      // Fresh, cookie-less browser context — we want the unauthenticated
      // /login + /register routes, not the admin's session.
      const visitorContext = await browser.newContext();
      const visitorPage = await visitorContext.newPage();
      try {
        await visitorPage.goto('/login');
        // The "Sign up" anchor is conditional on ``allow_signup`` —
        // when off it shouldn't render at all.
        await expect(
          visitorPage.getByRole('link', { name: /sign up/i }),
        ).toHaveCount(0);

        // Hitting /register directly still mounts the form, but
        // submitting it surfaces the "signup closed" alert because
        // the backend returns 404.
        await visitorPage.goto('/register');
        await visitorPage
          .getByLabel(/email/i, { exact: false })
          .first()
          .fill(uniqueEmail('e2e-closed'));
        await visitorPage
          .getByLabel(/full name/i)
          .fill('Closed Tester');
        await visitorPage
          .getByLabel(/^password/i, { exact: false })
          .first()
          .fill(VALID_PASSWORD);
        await visitorPage
          .getByLabel(/confirm password/i)
          .fill(VALID_PASSWORD);
        await visitorPage
          .getByRole('button', { name: /create account/i })
          .click();

        await expect(
          visitorPage.getByText(/signup is closed/i),
        ).toBeVisible();
      } finally {
        await visitorContext.close();
      }
    } finally {
      // Restore the suite-level state (open) for sibling specs.
      await setAuthConfig(adminPage.request, { allow_signup: true });
      await adminContext.close();
    }
  });

  test('signup happy path: register, verify by email link, log in', async ({
    browser,
  }) => {
    const visitorContext = await browser.newContext();
    const visitorPage = await visitorContext.newPage();
    try {
      const email = uniqueEmail('e2e-signup');

      await visitorPage.goto('/register');
      await visitorPage
        .getByLabel(/email/i, { exact: false })
        .first()
        .fill(email);
      await visitorPage
        .getByLabel(/full name/i)
        .fill('Signup Tester');
      await visitorPage
        .getByLabel(/^password/i, { exact: false })
        .first()
        .fill(VALID_PASSWORD);
      await visitorPage
        .getByLabel(/confirm password/i)
        .fill(VALID_PASSWORD);
      await visitorPage
        .getByRole('button', { name: /create account/i })
        .click();

      // "Check your email" success state.
      await expect(
        visitorPage.getByRole('heading', { name: /check your email/i }),
      ).toBeVisible();
      await expect(visitorPage.getByText(email)).toBeVisible();

      // The console mail backend prints to api stdout — give docker
      // a moment for the log line to flush before greppin'.
      let verifyPath = '';
      await expect
        .poll(
          () => {
            try {
              verifyPath = readLatestVerifyUrlForEmail(email);
              return Boolean(verifyPath);
            } catch {
              return false;
            }
          },
          {
            message: 'verify URL should appear in api container logs',
            timeout: 15000,
          },
        )
        .toBe(true);

      // Visit the verify link — landing on /verify-email with a token,
      // the page POSTs /auth/verify-email and shows the success alert.
      await visitorPage.goto(verifyPath);
      await expect(
        visitorPage.getByText(/your email is verified/i),
      ).toBeVisible();

      // Now we should be able to log in with the credentials. The
      // freshly-verified user has no second-factor enrolled and the
      // ``user`` role isn't on ``auth.require_2fa_for_roles`` (the
      // empty-list default), so opt-in 2FA grants a full session out
      // of password login — they land on the app shell, not /2fa.
      await visitorPage.goto('/login');
      await visitorPage
        .getByLabel(/email/i, { exact: false })
        .first()
        .fill(email);
      await visitorPage
        .getByLabel(/password/i, { exact: false })
        .first()
        .fill(VALID_PASSWORD);
      await visitorPage
        .getByRole('button', { name: /log in/i })
        .click();

      await expect(visitorPage).toHaveURL('/');
      await expect(
        visitorPage.getByRole('heading', { name: /Welcome/i }),
      ).toBeVisible();
    } finally {
      await visitorContext.close();
    }
  });

  test('login is refused before email verification when require_email_verification is true', async ({
    browser,
  }) => {
    const visitorContext = await browser.newContext();
    const visitorPage = await visitorContext.newPage();
    try {
      const email = uniqueEmail('e2e-unverified');

      // Register but DON'T click the verify link.
      const regResp = await visitorPage.request.post(
        `${API_URL}/auth/register`,
        {
          data: {
            email,
            password: VALID_PASSWORD,
            full_name: 'Unverified Tester',
            language: 'en',
          },
        },
      );
      expect([200, 201, 204].includes(regResp.status())).toBe(true);

      // Attempt to log in. fastapi-users collapses
      // "is_verified=False" + "wrong password" + "user disabled" into
      // a single 400 (gotcha #4) — the LoginPage renders the generic
      // ``invalidCredentials`` copy.
      await visitorPage.goto('/login');
      await visitorPage
        .getByLabel(/email/i, { exact: false })
        .first()
        .fill(email);
      await visitorPage
        .getByLabel(/password/i, { exact: false })
        .first()
        .fill(VALID_PASSWORD);
      await visitorPage
        .getByRole('button', { name: /log in/i })
        .click();

      await expect(
        visitorPage.getByText(/invalid email or password/i),
      ).toBeVisible();
      // We never left /login — no redirect to /2fa or /.
      await expect(visitorPage).toHaveURL(/\/login/);
    } finally {
      await visitorContext.close();
    }
  });

  test('expired or invalid verify token surfaces an error', async ({
    browser,
  }) => {
    const visitorContext = await browser.newContext();
    const visitorPage = await visitorContext.newPage();
    try {
      await visitorPage.goto('/verify-email?token=clearly-bogus-token');
      await expect(
        visitorPage.getByText(
          /verification link is invalid or has expired/i,
        ),
      ).toBeVisible();
    } finally {
      await visitorContext.close();
    }
  });

  test('duplicate email registration is rejected', async ({ browser }) => {
    const visitorContext = await browser.newContext();
    const visitorPage = await visitorContext.newPage();
    try {
      const email = uniqueEmail('e2e-dupe');

      // First registration — succeeds.
      const first = await visitorPage.request.post(
        `${API_URL}/auth/register`,
        {
          data: {
            email,
            password: VALID_PASSWORD,
            full_name: 'Dupe Tester',
            language: 'en',
          },
        },
      );
      expect([200, 201, 204].includes(first.status())).toBe(true);

      // Second registration — same email, surfaced through the UI as
      // the "email taken" alert (the API returns 409).
      await visitorPage.goto('/register');
      await visitorPage
        .getByLabel(/email/i, { exact: false })
        .first()
        .fill(email);
      await visitorPage
        .getByLabel(/full name/i)
        .fill('Dupe Tester (round 2)');
      await visitorPage
        .getByLabel(/^password/i, { exact: false })
        .first()
        .fill(VALID_PASSWORD);
      await visitorPage
        .getByLabel(/confirm password/i)
        .fill(VALID_PASSWORD);
      await visitorPage
        .getByRole('button', { name: /create account/i })
        .click();

      await expect(
        visitorPage.getByText(/account with that email already exists/i),
      ).toBeVisible();
    } finally {
      await visitorContext.close();
    }
  });

  test('signup form validates client-side', async ({ browser }) => {
    const visitorContext = await browser.newContext();
    const visitorPage = await visitorContext.newPage();
    try {
      await visitorPage.goto('/register');

      // The TextInput has ``type="email"`` which gates submit on the
      // browser's HTML5 email validity check. We need a value that
      // passes that (looks like ``local@host``) but fails Mantine's
      // stricter ``^\S+@\S+\.\S+$`` validator (which requires a
      // dotted domain). ``bad@x`` fits.
      await visitorPage
        .getByLabel(/email/i, { exact: false })
        .first()
        .fill('bad@x');
      await visitorPage
        .getByLabel(/^password/i, { exact: false })
        .first()
        .fill(VALID_PASSWORD);
      await visitorPage
        .getByLabel(/confirm password/i)
        .fill('does-not-match');
      await visitorPage
        .getByRole('button', { name: /create account/i })
        .click();

      await expect(
        visitorPage.getByText(/enter a valid email address/i),
      ).toBeVisible();
      await expect(
        visitorPage.getByText(/passwords do not match/i),
      ).toBeVisible();

      // Short password also flagged.
      await visitorPage
        .getByLabel(/email/i, { exact: false })
        .first()
        .fill('valid@example.com');
      await visitorPage
        .getByLabel(/^password/i, { exact: false })
        .first()
        .fill('short');
      await visitorPage
        .getByLabel(/confirm password/i)
        .fill('short');
      await visitorPage
        .getByRole('button', { name: /create account/i })
        .click();

      await expect(
        visitorPage.getByText(/password must be at least 8 characters/i),
      ).toBeVisible();
    } finally {
      await visitorContext.close();
    }
  });
});
