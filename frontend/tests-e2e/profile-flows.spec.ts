// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { expect, test } from '@playwright/test';

import {
  API_URL,
  createAndEnrolUserViaApi,
  loginAsSuperAdmin,
} from './helpers';

/**
 * Profile page flows that aren't already covered by the smoke /
 * extended specs:
 *  - Change password (and re-login with the new password)
 *  - Active sessions table renders the current device
 *  - Log out everywhere ends every session and bounces to /login
 */

const adminEmail = process.env.E2E_ADMIN_EMAIL;
const adminPassword = process.env.E2E_ADMIN_PASSWORD;
const adminTotpSecret = process.env.E2E_ADMIN_TOTP_SECRET;

const haveSmokeEnv = Boolean(adminEmail && adminPassword && adminTotpSecret);

test.skip(
  !haveSmokeEnv,
  'E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD / E2E_ADMIN_TOTP_SECRET must be set (run via `make smoke`).',
);

test.describe('Profile flows', () => {
  test.describe.configure({ mode: 'serial' });
  // Several specs in this file build TWO browser contexts and walk
  // through invite + accept + TOTP enrol + login. The default 30 s
  // budget is fine; tighter timeouts here just race the legitimately
  // expensive setup.
  test.describe.configure({ timeout: 30_000 });

  test('user can change their password via the profile page', async ({
    browser,
  }) => {
    // Provision a fresh enrolled user so we don't disturb the smoke
    // admin's password (other specs depend on it).
    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await loginAsSuperAdmin(adminPage);

    const userContext = await browser.newContext();
    const userPage = await userContext.newPage();
    const fresh = await createAndEnrolUserViaApi(
      adminPage.request,
      userPage.request,
    );
    // ``createAndEnrolUserViaApi`` leaves the cookie on userPage.request;
    // sync onto the browser context so navigation carries the session.
    const apiCookies = await userPage.request.storageState();
    await userContext.addCookies(apiCookies.cookies);

    const newPassword = 'New-Profile-Pw-12345!';

    try {
      await userPage.goto('/profile');
      await expect(
        userPage.getByRole('heading', { name: /your profile/i }),
      ).toBeVisible();

      // Fill the change-password form. Mantine's PasswordInput nests
      // the actual ``<input>`` inside a wrapper; anchor on the
      // ``[type=password]`` selector instead of getByLabel which can
      // resolve to the wrapper depending on Mantine's DOM shape.
      const pwInputs = userPage.locator('input[type="password"]');
      await pwInputs.nth(0).fill(newPassword);
      await pwInputs.nth(1).fill(newPassword);
      // ``.click()`` doesn't await the network request the click triggers,
      // so probing /auth/jwt/login immediately afterwards races the
      // password PATCH — on a slow Docker network the login lands before
      // the new hash is committed and returns 400 (fastapi-users uses 400
      // for bad credentials). Arm the response listener before clicking
      // and await it; that also surfaces a clearer error if the backend
      // itself rejects the password (HIBP, policy) instead of
      // misattributing it to "wrong password" on the next request.
      const updateResponse = userPage.waitForResponse(
        (resp) =>
          resp.url().endsWith('/api/users/me') &&
          resp.request().method() === 'PATCH',
      );
      await userPage
        .getByRole('button', { name: /^Update password$/i })
        .click();
      const updateResp = await updateResponse;
      expect(updateResp.status(), 'password PATCH must succeed').toBeLessThan(
        400,
      );

      // Verify end-to-end via a fresh context: new password works,
      // old one doesn't.
      const probe = await browser.newContext();
      try {
        const newLogin = await probe.request.post(
          `${API_URL}/auth/jwt/login`,
          { form: { username: fresh.email, password: newPassword } },
        );
        expect([200, 204]).toContain(newLogin.status());
        const oldLogin = await probe.request.post(
          `${API_URL}/auth/jwt/login`,
          { form: { username: fresh.email, password: 'Invitee-Pw-12345!' } },
        );
        expect(oldLogin.status()).toBeGreaterThanOrEqual(400);
        expect(oldLogin.status()).toBeLessThan(500);
      } finally {
        await probe.close();
      }
    } finally {
      await userContext.close();
      await adminContext.close();
    }
  });

  test('active sessions table shows the current device', async ({ page }) => {
    await loginAsSuperAdmin(page);
    await page.goto('/profile');

    // Wait for the sessions section to mount.
    await expect(
      page.getByRole('heading', { name: /active sessions/i }),
    ).toBeVisible();
    // The user just logged in — at least one session exists, and one
    // row carries the "This device" badge.
    await expect(page.getByText(/this device/i).first()).toBeVisible();
  });

  test('logout everywhere ends every session and bounces to /login', async ({
    browser,
  }) => {
    // Use a fresh user — wiping the smoke admin's sessions would
    // cascade-fail every spec that ran before (they share the same
    // session).
    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await loginAsSuperAdmin(adminPage);

    const userContext = await browser.newContext();
    const userPage = await userContext.newPage();
    await createAndEnrolUserViaApi(adminPage.request, userPage.request);
    const apiCookies = await userPage.request.storageState();
    await userContext.addCookies(apiCookies.cookies);

    try {
      await userPage.goto('/profile');
      // Stub ``window.confirm`` AFTER goto — navigation resets the
      // window object so a pre-goto stub doesn't survive.
      await userPage.evaluate(() => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (window as any).confirm = () => true;
      });
      await userPage
        .getByRole('button', { name: /log out everywhere/i })
        .click();

      // The handler navigates to /login with replace: true.
      await expect(userPage).toHaveURL(/\/login(\?|$)/);

      // Subsequent /users/me probe must come back unauth — server-side
      // session revoked.
      const meResp = await userPage.request.get(`${API_URL}/users/me`);
      expect(meResp.status()).toBe(401);
    } finally {
      await userContext.close();
      await adminContext.close();
    }
  });
});
