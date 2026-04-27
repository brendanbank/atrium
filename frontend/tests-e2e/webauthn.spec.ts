// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { expect, test } from '@playwright/test';

import { loginAndPassTOTP } from './helpers';

/**
 * WebAuthn challenge end-to-end: register a virtual authenticator via
 * the profile page, log out, and log back in — /2fa should fire the
 * ceremony automatically and land the user on the authenticated shell
 * without any second-factor input.
 *
 * Driven by CDP's WebAuthn domain. ``automaticPresenceSimulation=true``
 * stands in for the YubiKey tap; ``isUserVerified=true`` satisfies
 * even a UV=PREFERRED RP if settings ever flip.
 */

const API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000';

const email = process.env.E2E_ADMIN_EMAIL;
const password = process.env.E2E_ADMIN_PASSWORD;
const totpSecret = process.env.E2E_ADMIN_TOTP_SECRET;

test.beforeAll(() => {
  if (!email || !password || !totpSecret) {
    throw new Error(
      'E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD, and E2E_ADMIN_TOTP_SECRET must be set.',
    );
  }
});

test('admin can register a passkey and sign back in with it', async ({
  page,
  context,
}) => {
  // Attach a virtual authenticator before any WebAuthn call fires.
  const cdp = await context.newCDPSession(page);
  await cdp.send('WebAuthn.enable');
  const { authenticatorId } = await cdp.send(
    'WebAuthn.addVirtualAuthenticator',
    {
      options: {
        protocol: 'ctap2',
        transport: 'usb',
        hasResidentKey: false,
        hasUserVerification: true,
        isUserVerified: true,
        automaticPresenceSimulation: true,
      },
    },
  );

  try {
    // --- Step 1: full login via TOTP, then register a passkey. -------
    await loginAndPassTOTP(page, email!, password!, totpSecret!);
    await page.goto('/profile');

    const labelInput = page.getByPlaceholder(/YubiKey|TouchID/i);
    await labelInput.fill('E2E virtual key');
    // The inline "Register" button under the WebAuthn sub-section —
    // the Register key button in the modal would have the same label
    // but the modal isn't open here.
    await page
      .getByRole('button', { name: /^Register$/ })
      .click();

    await expect(page.getByText('E2E virtual key')).toBeVisible({
      timeout: 15_000,
    });

    // --- Step 2: log out server-side and wipe cookies. ---------------
    // The user-menu logout is a single-click flow but tying the test
    // to its Mantine selector is brittle. Calling the endpoint + hard
    // navigating gives the same observable state (no session cookie).
    const logoutResp = await page.request.post(`${API_URL}/auth/jwt/logout`);
    if (!logoutResp.ok() && logoutResp.status() !== 204) {
      throw new Error(`logout failed: ${logoutResp.status()}`);
    }
    await context.clearCookies();

    // --- Step 3: second login — WebAuthn fires automatically. --------
    await page.goto('/login');
    await page.locator('input[type="email"]').fill(email!);
    await page.locator('input[type="password"]').fill(password!);
    await page
      .getByRole('button', { name: /log.?in|sign.?in/i })
      .click();

    // Wait for /2fa to mount before asserting the final redirect;
    // without the intermediate sync, the test can race and miss the
    // window where the auto-ceremony is in flight.
    await page.waitForURL(/\/2fa/, { timeout: 10_000 });

    // /2fa mounts, auto-triggers the WebAuthn ceremony, virtual
    // authenticator responds, session is promoted, we redirect.
    await expect(page).toHaveURL('/', { timeout: 20_000 });
    await expect(
      page.getByRole('heading', { name: /Welcome/i }),
    ).toBeVisible();

    // --- Step 4: clean up the registered credential so reruns don't
    //             accumulate keys on the smoke admin. -----------------
    const creds = await page.request.get(
      `${API_URL}/auth/webauthn/credentials`,
    );
    const list = (await creds.json()) as Array<{ id: number; label: string }>;
    for (const c of list) {
      if (c.label === 'E2E virtual key') {
        await page.request.delete(
          `${API_URL}/auth/webauthn/credentials/${c.id}`,
        );
      }
    }
  } finally {
    await cdp.send('WebAuthn.removeVirtualAuthenticator', { authenticatorId });
  }
});
