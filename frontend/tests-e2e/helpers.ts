import { execSync } from 'child_process';

import type { Page } from '@playwright/test';
import { generate as generateTOTP } from 'otplib';

const API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000';

/**
 * Log in and clear the TOTP challenge using the smoke-seeded secret.
 *
 * Calls ``/auth/jwt/login`` + ``/auth/totp/verify`` directly against
 * the API so Playwright ends up holding the ``atrium_auth`` cookie
 * with ``totp_passed=True``. Navigation after that lands straight
 * on the authenticated shell. We deliberately skip driving the
 * ``PinInput`` via the UI — the smoke test is about the app shell,
 * not about the challenge widget's typing behaviour, which has
 * Vitest / backend coverage.
 *
 * The fixed TOTP secret is injected by ``make smoke`` via
 * ``E2E_ADMIN_TOTP_SECRET``.
 */
export async function loginAndPassTOTP(
  page: Page,
  email: string,
  password: string,
  totpSecret: string,
): Promise<void> {
  const loginResp = await page.request.post(`${API_URL}/auth/jwt/login`, {
    form: { username: email, password },
  });
  if (!loginResp.ok() && loginResp.status() !== 204) {
    throw new Error(`login failed: ${loginResp.status()}`);
  }

  const code = await generateTOTP({ secret: totpSecret });
  const verifyResp = await page.request.post(`${API_URL}/auth/totp/verify`, {
    data: { code },
  });
  if (!verifyResp.ok() && verifyResp.status() !== 204) {
    throw new Error(
      `totp verify failed: ${verifyResp.status()} ${await verifyResp.text()}`,
    );
  }

  // The cookie lives on the APIRequestContext — surface it to the
  // browser context so navigation carries the authenticated session.
  const cookies = await page.context().cookies();
  if (!cookies.some((c) => c.name === 'atrium_auth')) {
    // APIRequestContext and browser context sometimes have distinct
    // cookie jars (Playwright version dependent). Copy over.
    const apiCookies = await page.request.storageState();
    await page.context().addCookies(apiCookies.cookies);
  }

  await page.goto('/');
}


/**
 * Log in via the email-OTP challenge. Uses the console mail backend's
 * stdout to pick up the 6-digit code — we scrape the api container
 * logs, which is the standard pattern for e2e coverage of flows that
 * would otherwise need a real mailbox.
 *
 * The caller user must already have ``email_otp`` confirmed (see
 * ``seed_admin --email-otp``).
 */
export async function loginAndPassEmailOTP(
  page: Page,
  email: string,
  password: string,
): Promise<void> {
  const loginResp = await page.request.post(`${API_URL}/auth/jwt/login`, {
    form: { username: email, password },
  });
  if (!loginResp.ok() && loginResp.status() !== 204) {
    throw new Error(`login failed: ${loginResp.status()}`);
  }

  const reqResp = await page.request.post(
    `${API_URL}/auth/email-otp/request`,
  );
  if (!reqResp.ok() && reqResp.status() !== 204) {
    throw new Error(
      `email-otp request failed: ${reqResp.status()} ${await reqResp.text()}`,
    );
  }

  const code = readLatestEmailOTPCodeFromLogs(email);
  const verifyResp = await page.request.post(
    `${API_URL}/auth/email-otp/verify`,
    { data: { code } },
  );
  if (!verifyResp.ok() && verifyResp.status() !== 204) {
    throw new Error(
      `email-otp verify failed: ${verifyResp.status()} ${await verifyResp.text()}`,
    );
  }

  const cookies = await page.context().cookies();
  if (!cookies.some((c) => c.name === 'atrium_auth')) {
    const apiCookies = await page.request.storageState();
    await page.context().addCookies(apiCookies.cookies);
  }

  await page.goto('/');
}


function readLatestEmailOTPCodeFromLogs(recipientEmail: string): string {
  // The ConsoleMailBackend prints the rendered plain-text body to
  // the api container's stdout. Grab the last ~200 log lines and
  // walk backwards looking for the latest ``[email/console]`` block
  // addressed to ``recipientEmail`` whose body contains the code.
  const compose = process.env.E2E_COMPOSE_FILES ??
    '-f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.e2e.yml';
  // Compose file paths are relative to the project root; Playwright
  // runs from ``frontend/``, so cd up one level for the docker call.
  const raw = execSync(`docker compose ${compose} logs api --tail 200`, {
    encoding: 'utf-8',
    cwd: '..',
  });

  // Split into per-email blocks by the "==" ruler the console backend
  // emits between messages.
  const blocks = raw.split(/={50,}/);
  for (let i = blocks.length - 1; i >= 0; i--) {
    const block = blocks[i];
    if (
      block.includes('[email/console]') &&
      block.includes(`To:       ${recipientEmail}`) &&
      block.includes('template=email_otp_code')
    ) {
      // The default atrium email_otp_code template renders as
       // "Your sign-in code is 123456" once HTML-stripped. Match
       // flexibly so swapping the template wording doesn't break this.
      const match = block.match(/code is[:\s]*(\d{6})/i);
      if (match) return match[1];
    }
  }
  throw new Error(
    `no email_otp_code message for ${recipientEmail} found in api logs`,
  );
}
