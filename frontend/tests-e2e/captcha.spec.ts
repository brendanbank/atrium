// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { randomBytes } from 'crypto';

import { expect, test } from '@playwright/test';
import type { APIRequestContext } from '@playwright/test';

import { API_URL, loginAsAdmin, loginAsUser } from './helpers';

// crypto-backed uniqueness for fixture data — no security boundary.
function uniqueSuffix(): string {
  return `${Date.now()}-${randomBytes(4).readUInt32BE(0)}`;
}

/**
 * Phase 4 coverage — CAPTCHA (Turnstile + hCaptcha).
 *
 * What we can cover end-to-end:
 *
 *   * Negation — provider=``none`` (the atrium default) means no widget
 *     is rendered and no provider script tag is injected on the three
 *     pages that mount ``CaptchaWidget`` (/login, /register,
 *     /forgot-password). Existing flows still work.
 *   * Rendering — provider=``turnstile`` / ``hcaptcha`` injects the
 *     correct script tag and renders a container with the configured
 *     site key. We assert the *seam* is wired; we do not try to solve
 *     the challenge — Turnstile / hCaptcha both run anti-automation
 *     heuristics that defeat Playwright reliably.
 *   * Admin form — the Auth tab can flip the provider + site key and
 *     the change lands in the ``auth`` namespace.
 *   * Permission gate — a plain user without ``app_setting.manage``
 *     does not see the Auth tab, so they cannot see the captcha
 *     section.
 *
 * The strict success-vs-failure backend path (token=valid →
 * verify_captcha returns True; token=invalid → 400) is covered by the
 * unit tests in ``backend/tests/api/test_captcha.py``. The fail-open
 * posture (empty CAPTCHA_SECRET, network errors, unknown provider)
 * lives there too — the e2e stack runs with no CAPTCHA_SECRET set, so
 * driving registration through the UI with ``provider=turnstile`` and
 * a missing token would still 400 (no token is the one
 * unconditionally-rejected case in ``verify_captcha``); we therefore
 * stick to rendering assertions here.
 *
 * State management:
 *   * ``beforeAll`` snapshots the entire ``auth`` namespace via API.
 *   * ``afterAll`` puts the snapshot back so the next ``make smoke``
 *     run starts from the operator's chosen baseline.
 *   * Each spec cleans up after itself (try/finally) so a sibling
 *     never sees a half-mutated baseline.
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

// Cloudflare's documented "always passes" Turnstile site key — safe to
// embed in tests because it's published in their docs and only ever
// produces a green test token. Same idea for the hCaptcha key.
const TURNSTILE_TEST_SITE_KEY = '1x00000000000000000000AA';
const HCAPTCHA_TEST_SITE_KEY = '10000000-ffff-ffff-ffff-000000000001';

interface AuthCaptchaPatch {
  captcha_provider?: 'none' | 'turnstile' | 'hcaptcha';
  captcha_site_key?: string | null;
}

/**
 * PUT the ``auth`` namespace through the admin API. The endpoint
 * replaces the namespace, so we read the current value first and merge
 * the patch on top — keeps unrelated fields (signup toggles, password
 * policy, 2FA enforcement) intact when we're only flipping captcha
 * knobs. Mirrors the same helper in ``signup.spec`` /
 * ``password-policy.spec``.
 *
 * Caller must already hold a session with ``app_setting.manage``.
 */
async function setAuthConfig(
  request: APIRequestContext,
  patch: AuthCaptchaPatch,
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

// ---------------------------------------------------------------------------
// Suite — serial because each spec mutates the shared ``auth`` namespace
// and we don't want concurrent reads racing.
// ---------------------------------------------------------------------------

test.describe('captcha (Turnstile + hCaptcha)', () => {
  test.describe.configure({ mode: 'serial' });

  let snapshot: Record<string, unknown> | null = null;

  test.beforeAll(async ({ browser }) => {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    try {
      await loginAsAdmin(page);
      snapshot = await readAuthConfig(page.request);
      // Ensure the suite-wide baseline is provider=none so the
      // negation spec doesn't pick up a stale provider from a previous
      // failed run.
      await setAuthConfig(page.request, {
        captcha_provider: 'none',
        captcha_site_key: null,
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

  test('provider=none: no captcha widget rendered, normal flows work', async ({
    browser,
  }) => {
    // The suite-level beforeAll already set provider=none; assert the
    // current value matches expectation defensively before driving
    // through the UI so a flake elsewhere doesn't show up here as a
    // mysterious failure.
    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await loginAsAdmin(adminPage);
    try {
      const cfg = await readAuthConfig(adminPage.request);
      expect(cfg.captcha_provider ?? 'none').toBe('none');

      // Fresh, cookie-less context for the visitor probe — we want
      // the unauthenticated /login etc., not the admin shell.
      const visitorContext = await browser.newContext();
      const visitorPage = await visitorContext.newPage();
      try {
        for (const path of ['/login', '/register', '/forgot-password']) {
          await visitorPage.goto(path);
          // Neither widget container should render.
          await expect(visitorPage.locator('.cf-turnstile')).toHaveCount(0);
          await expect(visitorPage.locator('.h-captcha')).toHaveCount(0);
          // No provider script tag should be injected — the
          // CaptchaWidget early-returns when provider==='none'.
          await expect(
            visitorPage.locator(
              'script[src*="challenges.cloudflare.com/turnstile"]',
            ),
          ).toHaveCount(0);
          await expect(
            visitorPage.locator('script[src*="hcaptcha.com/1/api.js"]'),
          ).toHaveCount(0);
        }
      } finally {
        await visitorContext.close();
      }

      // Sanity: an admin can still log in normally with no captcha
      // gating the flow. ``loginAsAdmin`` exercises the API path
      // (login + totp/verify) which is what the LoginPage drives —
      // re-running it on a fresh context confirms the gate is open.
      const sanityContext = await browser.newContext();
      const sanityPage = await sanityContext.newPage();
      try {
        await loginAsAdmin(sanityPage);
        // ``loginAsAdmin`` ends with ``page.goto('/')`` — if the
        // login flow worked, the page is no longer at /login.
        await expect(sanityPage).not.toHaveURL(/\/login/);
      } finally {
        await sanityContext.close();
      }
    } finally {
      // No mutation in this spec, but keep the contract uniform.
      await adminContext.close();
    }
  });

  test('provider=turnstile: widget script + container render on /register', async ({
    browser,
  }) => {
    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await loginAsAdmin(adminPage);

    try {
      await setAuthConfig(adminPage.request, {
        captcha_provider: 'turnstile',
        captcha_site_key: TURNSTILE_TEST_SITE_KEY,
      });

      const visitorContext = await browser.newContext();
      const visitorPage = await visitorContext.newPage();
      try {
        await visitorPage.goto('/register');

        // The container is rendered synchronously by React — assert
        // the .cf-turnstile div with the configured site key is
        // present.
        const widget = visitorPage.locator('.cf-turnstile');
        await expect(widget).toBeVisible();
        await expect(widget).toHaveAttribute(
          'data-sitekey',
          TURNSTILE_TEST_SITE_KEY,
        );

        // The provider script is injected by ``ensureScript`` inside
        // a useEffect, so it lands a tick after mount. ``expect.poll``
        // waits without sleeping.
        await expect
          .poll(
            async () => {
              return visitorPage.locator(
                'script[src*="challenges.cloudflare.com/turnstile/v0/api.js"]',
              ).count();
            },
            {
              message: 'Turnstile script tag should be injected on mount',
              timeout: 5000,
            },
          )
          .toBeGreaterThan(0);

        // hCaptcha's script must NOT be loaded — providers are
        // mutually exclusive.
        await expect(
          visitorPage.locator('script[src*="hcaptcha.com/1/api.js"]'),
        ).toHaveCount(0);
      } finally {
        await visitorContext.close();
      }
    } finally {
      // Restore baseline for sibling specs.
      await setAuthConfig(adminPage.request, {
        captcha_provider: 'none',
        captcha_site_key: null,
      });
      await adminContext.close();
    }
  });

  test('provider=hcaptcha: widget script + container render on /login', async ({
    browser,
  }) => {
    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await loginAsAdmin(adminPage);

    try {
      await setAuthConfig(adminPage.request, {
        captcha_provider: 'hcaptcha',
        captcha_site_key: HCAPTCHA_TEST_SITE_KEY,
      });

      const visitorContext = await browser.newContext();
      const visitorPage = await visitorContext.newPage();
      try {
        await visitorPage.goto('/login');

        const widget = visitorPage.locator('.h-captcha');
        await expect(widget).toBeVisible();
        await expect(widget).toHaveAttribute(
          'data-sitekey',
          HCAPTCHA_TEST_SITE_KEY,
        );

        await expect
          .poll(
            async () => {
              return visitorPage.locator(
                'script[src*="hcaptcha.com/1/api.js"]',
              ).count();
            },
            {
              message: 'hCaptcha script tag should be injected on mount',
              timeout: 5000,
            },
          )
          .toBeGreaterThan(0);

        // Turnstile script must NOT be loaded.
        await expect(
          visitorPage.locator(
            'script[src*="challenges.cloudflare.com/turnstile"]',
          ),
        ).toHaveCount(0);
      } finally {
        await visitorContext.close();
      }
    } finally {
      await setAuthConfig(adminPage.request, {
        captcha_provider: 'none',
        captcha_site_key: null,
      });
      await adminContext.close();
    }
  });

  test('admin can switch captcha provider through Auth tab', async ({
    browser,
  }) => {
    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await loginAsAdmin(adminPage);

    try {
      await adminPage.goto('/admin?tab=auth');

      // The Auth tab carries one Save button covering the whole
      // namespace. Locate the Captcha section by its title, then
      // operate on the form controls within it. The Provider Select is
      // a Mantine combobox — click to open, then click the option
      // labelled "Cloudflare Turnstile".
      await expect(
        adminPage.getByRole('heading', { name: /CAPTCHA/i }),
      ).toBeVisible();

      // Mantine v9's Select renders the input wrapped in a Combobox
      // primitive whose dropdown lives in a portal. Click the input
      // to open the dropdown, then pick the option by its visible
      // text rather than role — the option DOM has differed across
      // Mantine point releases.
      await adminPage.getByLabel(/^Provider$/i).first().click();
      await adminPage
        .locator('[role="option"], [data-combobox-option]')
        .filter({ hasText: 'Cloudflare Turnstile' })
        .first()
        .click();

      const typedKey = `e2e-${uniqueSuffix()}`;
      const siteKeyInput = adminPage.getByLabel(/^Site key$/i).first();
      await siteKeyInput.fill(typedKey);

      const saveButton = adminPage.getByRole('button', { name: /^Save$/ });
      // Wait for the PUT to land before reading the namespace, so we
      // don't race the optimistic save.
      const savePromise = adminPage.waitForResponse(
        (resp) =>
          resp.url().endsWith('/admin/app-config/auth') &&
          resp.request().method() === 'PUT' &&
          resp.ok(),
      );
      await saveButton.last().click();
      await savePromise;

      const cfg = await readAuthConfig(adminPage.request);
      expect(cfg.captcha_provider).toBe('turnstile');
      expect(cfg.captcha_site_key).toBe(typedKey);
    } finally {
      // Restore baseline for sibling specs / the snapshot.
      await setAuthConfig(adminPage.request, {
        captcha_provider: 'none',
        captcha_site_key: null,
      });
      await adminContext.close();
    }
  });

  test("non-admin doesn't see captcha config in the Auth tab", async ({
    browser,
  }) => {
    // ``loginAsUser`` mints + logs in a fresh ``user``-roled account.
    // That role holds no permissions by default, so neither
    // ``app_setting.manage`` nor any other admin perm is granted — the
    // Auth tab is entirely hidden from them.
    const userContext = await browser.newContext();
    const userPage = await userContext.newPage();

    try {
      await loginAsUser(userPage);
      await userPage.goto('/admin');

      // Wait for the always-present Users tab so we know the page
      // mounted before asserting the Auth tab is absent.
      await expect(
        userPage.getByRole('tab', { name: /Users|Gebruikers/i }),
      ).toBeVisible();
      await expect(
        userPage.getByRole('tab', { name: /^Auth$/i }),
      ).toHaveCount(0);

      // Direct-URL access falls through to the default Users tab —
      // AdminPage validates ``?tab=auth`` against the user's perms.
      await userPage.goto('/admin?tab=auth');
      await expect(
        userPage.getByRole('tab', { name: /Users|Gebruikers/i }),
      ).toHaveAttribute('aria-selected', 'true');

      // And the captcha-specific UI must not be reachable: no
      // "CAPTCHA" heading, no "Site key" or "Provider" inputs — those
      // belong to the AuthAdmin component which never mounts for this
      // user.
      await expect(
        userPage.getByRole('heading', { name: /CAPTCHA/i }),
      ).toHaveCount(0);
    } finally {
      await userContext.close();
    }
  });
});
