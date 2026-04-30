// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { expect, test } from '@playwright/test';
import { generate as generateTOTP } from 'otplib';

import {
  API_URL,
  createAndEnrolUserViaApi,
  loginAsSuperAdmin,
  readLatestEmailLogEntry,
} from './helpers';

/**
 * Forgot/reset password flow — the only un-2FA'd account-recovery path,
 * so it deserves a UI-level spec. Drives the SPA forms, scrapes the
 * console mail backend for the token, and confirms login with the new
 * password.
 */

const adminEmail = process.env.E2E_ADMIN_EMAIL;
const adminPassword = process.env.E2E_ADMIN_PASSWORD;
const adminTotpSecret = process.env.E2E_ADMIN_TOTP_SECRET;

const haveSmokeEnv = Boolean(adminEmail && adminPassword && adminTotpSecret);

test.skip(
  !haveSmokeEnv,
  'E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD / E2E_ADMIN_TOTP_SECRET must be set (run via `make smoke`).',
);

test.describe('Forgot / reset password', () => {
  test.describe.configure({ mode: 'serial' });

  test('user can request reset, receive token via email, set new password', async ({
    browser,
  }) => {
    // Provision a fresh enrolled user via the admin API so we have a
    // known account to drive the recovery flow against.
    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await loginAsSuperAdmin(adminPage);

    const visitorContext = await browser.newContext();
    const visitorPage = await visitorContext.newPage();
    const fresh = await createAndEnrolUserViaApi(
      adminPage.request,
      visitorPage.request,
    );
    // Drop the cookie set by the createAndEnrol flow — we want the
    // recovery surface as an unauth visitor.
    await visitorContext.clearCookies();

    try {
      // ---- Submit /forgot-password -----------------------------------
      await visitorPage.goto('/forgot-password');
      await expect(
        visitorPage.getByRole('heading', { name: /reset your password/i }),
      ).toBeVisible();
      await visitorPage.getByLabel(/email/i).fill(fresh.email);
      await visitorPage
        .getByRole('button', { name: /send reset link/i })
        .click();
      await expect(
        visitorPage.getByText(/sent a reset link/i),
      ).toBeVisible();

      // ---- Pull the token out of the password_reset email -----------
      // The password_reset template carries an explicit "Or paste this
      // link: {{ reset_url }}" line outside the anchor (mirrors the
      // ``email_verify`` template) so the URL survives the sender's
      // tag-strip into the plain-text body.
      const token = await (async () => {
        for (let attempt = 0; attempt < 10; attempt++) {
          try {
            const entry = readLatestEmailLogEntry(
              'password_reset',
              fresh.email,
            );
            const match = entry.body_text.match(
              /\/reset-password\?token=([^\s"'<>]+)/,
            );
            if (match) return match[1];
          } catch {
            // Email log line might not be in the tail buffer yet.
          }
          await visitorPage.waitForTimeout(300);
        }
        throw new Error('reset token never appeared in api logs');
      })();

      // ---- Drive /reset-password with the token ---------------------
      const newPassword = 'Reset-Pw-NEW-12345!';
      await visitorPage.goto(`/reset-password?token=${token}`);
      await expect(
        visitorPage.getByRole('heading', { name: /choose a new password/i }),
      ).toBeVisible();
      await visitorPage
        .getByLabel(/^new password/i)
        .fill(newPassword);
      await visitorPage
        .getByLabel(/confirm password/i)
        .fill(newPassword);
      await visitorPage
        .getByRole('button', { name: /update password/i })
        .click();

      // ResetPasswordPage redirects to /login on success.
      await expect(visitorPage).toHaveURL(/\/login(\?|$)/);

      // ---- New password works against the API; old one doesn't -----
      const newLoginContext = await browser.newContext();
      try {
        const newLogin = await newLoginContext.request.post(
          `${API_URL}/auth/jwt/login`,
          { form: { username: fresh.email, password: newPassword } },
        );
        expect([200, 204]).toContain(newLogin.status());

        // The reset doesn't wipe TOTP, so the second factor still gates
        // the session — drive it through to confirm the account is
        // fully recoverable.
        const code = await generateTOTP({ secret: fresh.totpSecret });
        const totpVerify = await newLoginContext.request.post(
          `${API_URL}/auth/totp/verify`,
          { data: { code } },
        );
        expect([200, 204]).toContain(totpVerify.status());

        // Old password rejected (fastapi-users returns 400, not 401).
        const oldLoginContext = await browser.newContext();
        try {
          const oldLogin = await oldLoginContext.request.post(
            `${API_URL}/auth/jwt/login`,
            { form: { username: fresh.email, password: 'Invitee-Pw-12345!' } },
          );
          expect(oldLogin.status()).toBeGreaterThanOrEqual(400);
          expect(oldLogin.status()).toBeLessThan(500);
        } finally {
          await oldLoginContext.close();
        }
      } finally {
        await newLoginContext.close();
      }
    } finally {
      await visitorContext.close();
      await adminContext.close();
    }
  });

  test('reset-password without token shows the missing-token alert', async ({
    page,
  }) => {
    await page.goto('/reset-password');
    await expect(
      page.getByText(/missing reset token/i),
    ).toBeVisible();
  });

  test('reset-password rejects mismatched confirmation client-side', async ({
    page,
  }) => {
    // Any non-empty token gets us past the missing-token early return —
    // the test asserts the client-side validator fires before the API
    // call goes out.
    await page.goto('/reset-password?token=fake-token-for-validation-test');
    await page.getByLabel(/^new password/i).fill('aaaaaaaaaa');
    await page.getByLabel(/confirm password/i).fill('bbbbbbbbbb');
    await page.getByRole('button', { name: /update password/i }).click();
    // Mantine's useForm renders the validator's return string under the
    // input. The exact text comes from ``acceptInvite.passwordMismatch``.
    await expect(
      page.getByText(/passwords do not match|wachtwoorden komen niet overeen/i),
    ).toBeVisible();
  });
});
