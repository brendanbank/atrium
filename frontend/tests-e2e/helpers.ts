// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { execSync } from 'child_process';

import type { APIRequestContext, Page } from '@playwright/test';
import { generate as generateTOTP } from 'otplib';

export const API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000';

/**
 * Convenience: log in as the smoke-seeded super_admin (the same
 * account ``loginAndPassTOTP`` uses when given the smoke env vars).
 * The seed-step in ``make smoke-up`` grants the ``super_admin`` role,
 * so this is just a thin alias kept around for readability when a
 * spec specifically depends on super-admin authority.
 */
export async function loginAsSuperAdmin(page: Page): Promise<void> {
  const email = process.env.E2E_ADMIN_EMAIL;
  const password = process.env.E2E_ADMIN_PASSWORD;
  const totpSecret = process.env.E2E_ADMIN_TOTP_SECRET;
  if (!email || !password || !totpSecret) {
    throw new Error(
      'E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD / E2E_ADMIN_TOTP_SECRET must be set.',
    );
  }
  await loginAndPassTOTP(page, email, password, totpSecret);
}

/**
 * Alias of ``loginAsSuperAdmin`` for specs whose dependency is "any
 * admin who can manage app_setting" rather than super-admin
 * specifically. The seeded admin holds both roles, so they're
 * indistinguishable at the API level — the alias just keeps spec
 * intent readable.
 */
export async function loginAsAdmin(page: Page): Promise<void> {
  await loginAsSuperAdmin(page);
}

/**
 * Provision a fresh non-admin user (``user`` role only) via the
 * invite + accept flow, enrol them in TOTP, and leave the supplied
 * ``page`` logged in as that user with a fully promoted session.
 *
 * Atrium ships a single seeded admin per smoke run, so any spec that
 * needs to assert a *negative* permission case (no Branding tab,
 * /profile language preference) has to mint its own non-admin. We
 * piggy-back on the admin's API session to mint the invite, then drop
 * cookies and accept + enrol the new user.
 *
 * Returns the credentials so the caller can re-login the same user
 * across logout/login boundaries (e.g. the "preferred_language
 * persists" spec).
 */
export interface ProvisionedUser {
  email: string;
  password: string;
  totpSecret: string;
}

export async function loginAsUser(page: Page): Promise<ProvisionedUser> {
  const adminEmail = process.env.E2E_ADMIN_EMAIL;
  const adminPassword = process.env.E2E_ADMIN_PASSWORD;
  const adminTotpSecret = process.env.E2E_ADMIN_TOTP_SECRET;
  if (!adminEmail || !adminPassword || !adminTotpSecret) {
    throw new Error(
      'E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD / E2E_ADMIN_TOTP_SECRET must be set.',
    );
  }
  const browserContext = page.context();
  const reqCtx = browserContext.request;

  // Authenticate as admin, mint the invite.
  const adminLogin = await reqCtx.post(`${API_URL}/auth/jwt/login`, {
    form: { username: adminEmail, password: adminPassword },
  });
  if (!adminLogin.ok() && adminLogin.status() !== 204) {
    throw new Error(`admin login failed: ${adminLogin.status()}`);
  }
  const adminCode = await generateTOTP({ secret: adminTotpSecret });
  const adminVerify = await reqCtx.post(`${API_URL}/auth/totp/verify`, {
    data: { code: adminCode },
  });
  if (!adminVerify.ok() && adminVerify.status() !== 204) {
    throw new Error(`admin totp verify failed: ${adminVerify.status()}`);
  }

  const email = `e2e-user-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
  const password = 'user-pw-12345';
  const inviteResp = await reqCtx.post(`${API_URL}/invites`, {
    data: { email, full_name: 'E2E User', role_codes: ['user'] },
  });
  if (inviteResp.status() !== 201) {
    throw new Error(
      `invite create failed: ${inviteResp.status()} ${await inviteResp.text()}`,
    );
  }
  const invite = (await inviteResp.json()) as { token: string };

  // Wipe the admin cookie before any user-side request so we don't
  // accept the invite under the admin session.
  await browserContext.clearCookies();

  // Accept invite (no auth needed), then log the user in fresh.
  const acceptResp = await reqCtx.post(`${API_URL}/invites/accept`, {
    data: { token: invite.token, password },
  });
  if (!acceptResp.ok() && acceptResp.status() !== 204) {
    throw new Error(
      `invite accept failed: ${acceptResp.status()} ${await acceptResp.text()}`,
    );
  }
  const userLogin = await reqCtx.post(`${API_URL}/auth/jwt/login`, {
    form: { username: email, password },
  });
  if (!userLogin.ok() && userLogin.status() !== 204) {
    throw new Error(`user login failed: ${userLogin.status()}`);
  }

  // Enrol TOTP and confirm — this flips ``totp_passed=True`` on the
  // current ``auth_sessions`` row so domain endpoints accept the
  // cookie. Far simpler than driving the /2fa setup picker through
  // the browser for every spec that needs a non-admin.
  const setupResp = await reqCtx.post(`${API_URL}/auth/totp/setup`);
  if (!setupResp.ok()) {
    throw new Error(
      `totp setup failed: ${setupResp.status()} ${await setupResp.text()}`,
    );
  }
  const { secret } = (await setupResp.json()) as { secret: string };
  const code = await generateTOTP({ secret });
  const confirmResp = await reqCtx.post(`${API_URL}/auth/totp/confirm`, {
    data: { code },
  });
  if (!confirmResp.ok() && confirmResp.status() !== 204) {
    throw new Error(
      `totp confirm failed: ${confirmResp.status()} ${await confirmResp.text()}`,
    );
  }

  // Mirror cookies onto the browser jar in case Playwright keeps them
  // separate on this version, then navigate.
  const cookies = await browserContext.cookies();
  if (!cookies.some((c) => c.name === 'atrium_auth')) {
    const apiCookies = await reqCtx.storageState();
    await browserContext.addCookies(apiCookies.cookies);
  }
  await page.goto('/');
  return { email, password, totpSecret: secret };
}

/**
 * PUT the ``auth`` namespace through the admin API. Reads the current
 * value first and merges the patch on top so unrelated fields stay
 * intact when only flipping a single knob (e.g. ``allow_signup``).
 *
 * Caller must already hold a session with ``app_setting.manage``.
 */
export async function setAuthConfig(
  request: APIRequestContext,
  patch: Partial<{
    allow_self_delete: boolean;
    delete_grace_days: number;
    allow_signup: boolean;
    signup_default_role_code: string;
    require_email_verification: boolean;
  }>,
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
 * PUT the ``brand`` namespace through the admin API. Caller must
 * already hold a session with ``app_setting.manage`` (an admin /
 * super_admin login on ``request``).
 */
export async function setBrandConfig(
  request: APIRequestContext,
  patch: Partial<{
    name: string;
    logo_url: string | null;
    support_email: string | null;
    preset: 'default' | 'dark-glass' | 'classic';
    overrides: Record<string, string>;
  }>,
): Promise<void> {
  const cur = await request.get(`${API_URL}/admin/app-config`);
  if (!cur.ok()) {
    throw new Error(`app-config read failed: ${cur.status()}`);
  }
  const body = (await cur.json()) as { brand?: Record<string, unknown> };
  const merged = { ...(body.brand ?? {}), ...patch };
  const resp = await request.put(`${API_URL}/admin/app-config/brand`, {
    data: merged,
  });
  if (!resp.ok()) {
    throw new Error(`brand put failed: ${resp.status()} ${await resp.text()}`);
  }
}

/**
 * PUT the ``i18n`` namespace through the admin API. Caller must
 * already hold a session with ``app_setting.manage``.
 */
export async function setI18nConfig(
  request: APIRequestContext,
  patch: Partial<{
    enabled_locales: string[];
    overrides: Record<string, Record<string, string>>;
  }>,
): Promise<void> {
  const cur = await request.get(`${API_URL}/admin/app-config`);
  if (!cur.ok()) {
    throw new Error(`app-config read failed: ${cur.status()}`);
  }
  const body = (await cur.json()) as { i18n?: Record<string, unknown> };
  const merged = { ...(body.i18n ?? {}), ...patch };
  const resp = await request.put(`${API_URL}/admin/app-config/i18n`, {
    data: merged,
  });
  if (!resp.ok()) {
    throw new Error(`i18n put failed: ${resp.status()} ${await resp.text()}`);
  }
}

/**
 * Reset both branding and i18n namespaces to their atrium defaults.
 * Used by branding / translations spec teardown so no test leaks an
 * override into a sibling spec or the next ``make smoke`` run.
 */
export async function resetBrandAndI18n(
  request: APIRequestContext,
): Promise<void> {
  // Atrium defaults from app.services.app_config.BrandConfig /
  // I18nConfig — kept inline rather than hard-coding the model
  // import path. If a host app extends defaults, override these
  // by passing the shape they want via setBrandConfig directly.
  const brandResp = await request.put(`${API_URL}/admin/app-config/brand`, {
    data: {
      name: 'Atrium',
      logo_url: '/logo.svg',
      support_email: null,
      preset: 'default',
      overrides: {},
    },
  });
  if (!brandResp.ok()) {
    throw new Error(
      `brand reset failed: ${brandResp.status()} ${await brandResp.text()}`,
    );
  }
  const i18nResp = await request.put(`${API_URL}/admin/app-config/i18n`, {
    data: { enabled_locales: ['en', 'nl'], overrides: {} },
  });
  if (!i18nResp.ok()) {
    throw new Error(
      `i18n reset failed: ${i18nResp.status()} ${await i18nResp.text()}`,
    );
  }
}

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


/**
 * Drive the invite + accept + TOTP enrolment flow end-to-end against
 * the API and return a fresh user that's logged in on
 * ``inviteeRequest`` with a full-2FA session (i.e. ``totp_passed=True``
 * — domain endpoints will accept their cookie).
 *
 * We avoid driving the UI for this because the value of these specs
 * is the maintenance / account-deletion behaviour, not yet-another
 * pass through the invite flow that ``invite-flow.spec`` already
 * covers.
 *
 * ``adminRequest`` must already hold an admin / super_admin session
 * (use ``loginAsSuperAdmin`` first). ``inviteeRequest`` should be a
 * fresh, cookie-less request context so the invitee's
 * ``atrium_auth`` cookie doesn't collide with the caller's.
 */
export interface SeededUser {
  email: string;
  password: string;
  totpSecret: string;
  inviteId: number;
}

export async function createAndEnrolUserViaApi(
  adminRequest: APIRequestContext,
  inviteeRequest: APIRequestContext,
  opts: { roleCodes?: string[] } = {},
): Promise<SeededUser> {
  const email = `e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
  const password = 'invitee-pw-12345';

  const createResp = await adminRequest.post(`${API_URL}/invites`, {
    data: {
      email,
      full_name: 'E2E Account',
      role_codes: opts.roleCodes ?? ['user'],
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

  // Log the freshly-created user in to obtain an auth cookie on
  // ``inviteeRequest``.
  const loginResp = await inviteeRequest.post(`${API_URL}/auth/jwt/login`, {
    form: { username: email, password },
  });
  if (!loginResp.ok() && loginResp.status() !== 204) {
    throw new Error(`login failed: ${loginResp.status()}`);
  }

  // Enroll TOTP and confirm with the first code so the session flips
  // to ``totp_passed=True``.
  const setupResp = await inviteeRequest.post(`${API_URL}/auth/totp/setup`);
  if (!setupResp.ok()) {
    throw new Error(
      `totp setup failed: ${setupResp.status()} ${await setupResp.text()}`,
    );
  }
  const { secret } = (await setupResp.json()) as { secret: string };
  const code = await generateTOTP({ secret });
  const confirmResp = await inviteeRequest.post(
    `${API_URL}/auth/totp/confirm`,
    { data: { code } },
  );
  if (!confirmResp.ok() && confirmResp.status() !== 204) {
    throw new Error(
      `totp confirm failed: ${confirmResp.status()} ${await confirmResp.text()}`,
    );
  }

  return { email, password, totpSecret: secret, inviteId: created.id };
}

/**
 * Drive ``POST /auth/jwt/login`` + ``POST /auth/totp/verify`` on a
 * given page using a pre-seeded TOTP secret. The caller-page-context
 * variant of ``loginAndPassTOTP`` that doesn't navigate afterwards —
 * useful when you want to inspect the post-login URL yourself.
 */
export async function loginPassTOTPNoNav(
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
  const cookies = await page.context().cookies();
  if (!cookies.some((c) => c.name === 'atrium_auth')) {
    const apiCookies = await page.request.storageState();
    await page.context().addCookies(apiCookies.cookies);
  }
}

/**
 * Set the ``system`` app-config namespace via the admin API. Caller
 * must hold ``app_setting.manage`` (super_admin / admin).
 */
export async function setSystemConfig(
  request: APIRequestContext,
  patch: {
    maintenance_mode?: boolean;
    maintenance_message?: string;
    announcement?: string | null;
    announcement_level?: 'info' | 'warning' | 'critical';
  },
): Promise<void> {
  // The PUT endpoint replaces the namespace, so we read the current
  // value first and merge our patch on top — keeps unrelated fields
  // intact if a previous test (or the admin) had configured them.
  const cur = await request.get(`${API_URL}/admin/app-config`);
  if (!cur.ok()) {
    throw new Error(
      `admin app-config read failed: ${cur.status()} ${await cur.text()}`,
    );
  }
  const body = (await cur.json()) as { system?: Record<string, unknown> };
  const merged = { ...(body.system ?? {}), ...patch };
  const resp = await request.put(`${API_URL}/admin/app-config/system`, {
    data: merged,
  });
  if (!resp.ok()) {
    throw new Error(
      `system put failed: ${resp.status()} ${await resp.text()}`,
    );
  }
}

/**
 * Read the most recent ``[email/console]`` block out of the api
 * container's stdout that targets ``recipientEmail`` and was rendered
 * from ``template``. Returns the parsed ``Subject:`` line plus the
 * plain-text body so a spec can assert the variant the recipient
 * actually received (subject in their preferred locale, fallback to
 * EN when the host hasn't authored their language yet).
 *
 * The console backend prints ``Subject:  <one line>`` followed by a
 * separator and the plain-text body — this helper splits on those
 * boundaries rather than re-parsing arbitrary HTML.
 */
export interface EmailLogEntry {
  subject: string;
  body_text: string;
}

export function readLatestEmailLogEntry(
  template: string,
  recipientEmail: string,
): EmailLogEntry {
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
      block.includes(`template=${template}`)
    ) {
      // Strip docker-compose's leading ``api  | `` prefix from each
      // line so the body text reads cleanly. The pipe-prefix only
      // appears when ``docker compose logs`` interleaves containers,
      // but stripping unconditionally is harmless.
      const cleaned = block
        .split('\n')
        .map((l) => l.replace(/^[a-zA-Z0-9_-]+\s+\|\s?/, ''))
        .join('\n');
      const subjectMatch = cleaned.match(/Subject:\s+(.+)/);
      const subject = subjectMatch ? subjectMatch[1].trim() : '';
      // The console block separates headers / body / html-marker with
      // a 70-char ``-`` rule. The text body is the chunk between the
      // first and second rule (or block end if no html alternative).
      const parts = cleaned.split(/-{50,}/);
      // parts[0] = header, parts[1] = text body, parts[2] = html marker
      const body_text = (parts[1] ?? '').trim();
      return { subject, body_text };
    }
  }
  throw new Error(
    `no ${template} message for ${recipientEmail} found in api logs`,
  );
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
