// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { expect, test } from '@playwright/test';

import { loginAndPassEmailOTP } from './helpers';

/**
 * Smoke for the email-OTP challenge path: the second e2e admin is
 * pre-enrolled with ``email_otp_confirmed=True`` (see
 * ``seed_admin --email-otp``). This test logs them in via
 * ``/auth/email-otp/request`` + ``/auth/email-otp/verify``, scraping
 * the plaintext code from the api container's console log output —
 * same trick the backend's ConsoleMailBackend uses in dev.
 */

const email = process.env.E2E_EMAIL_OTP_EMAIL;
const password = process.env.E2E_EMAIL_OTP_PASSWORD;

test.beforeAll(() => {
  if (!email || !password) {
    throw new Error(
      'E2E_EMAIL_OTP_EMAIL and E2E_EMAIL_OTP_PASSWORD must be set for the email-OTP smoke.',
    );
  }
});

test('user can log in via the email-OTP challenge', async ({ page }) => {
  await loginAndPassEmailOTP(page, email!, password!);

  await expect(page).toHaveURL('/');
  await expect(page.getByRole('heading', { name: /Welcome/i })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Profile' })).toBeVisible();
});
