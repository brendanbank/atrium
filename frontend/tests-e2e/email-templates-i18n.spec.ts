// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { execSync } from 'child_process';

import { expect, test } from '@playwright/test';
import type { APIRequestContext } from '@playwright/test';

import {
  API_URL,
  loginAsAdmin,
  loginAsUser,
  readLatestEmailLogEntry,
  setAuthConfig,
} from './helpers';

/**
 * Phase 11 — multi-language email templates.
 *
 * Each (key, locale) row in ``email_templates`` is editable
 * independently; the sender resolves a recipient's
 * ``preferred_language`` to the matching variant and falls back to EN
 * when no translation exists. These specs exercise:
 *
 *   1. Admin can edit a template's NL variant without touching EN.
 *   2. The verify-email rendered for a freshly-registered NL user is
 *      the NL variant (subject + body).
 *   3. A user whose ``preferred_language`` is set to a locale we don't
 *      ship (``es``) still receives an EN-rendered password reset.
 *   4. A non-admin (user role) doesn't see the Email templates tab.
 *
 * Smoke-only: the docker-log scraping pattern relies on the api
 * container running under compose with ``MAIL_BACKEND=console``.
 *
 * Required env (set by ``make smoke-up``):
 *   E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD / E2E_ADMIN_TOTP_SECRET
 */

const adminEmail = process.env.E2E_ADMIN_EMAIL;
const adminPassword = process.env.E2E_ADMIN_PASSWORD;
const adminTotpSecret = process.env.E2E_ADMIN_TOTP_SECRET;

interface EmailTemplateRow {
  key: string;
  locale: string;
  subject: string;
  body_html: string;
  description: string | null;
  updated_at: string;
}

/**
 * Read the (key, locale) variant via the admin API. Caller must hold
 * a session with ``email_template.manage`` (the seeded super_admin).
 */
async function getEmailTemplate(
  request: APIRequestContext,
  key: string,
  locale: string,
): Promise<EmailTemplateRow> {
  const resp = await request.get(
    `${API_URL}/admin/email-templates/${key}/${locale}`,
  );
  if (!resp.ok()) {
    throw new Error(
      `get template ${key}/${locale} failed: ${resp.status()} ${await resp.text()}`,
    );
  }
  return (await resp.json()) as EmailTemplateRow;
}

/**
 * PATCH a (key, locale) variant. Returns the updated row.
 */
async function patchEmailTemplate(
  request: APIRequestContext,
  key: string,
  locale: string,
  payload: { subject?: string; body_html?: string; description?: string | null },
): Promise<EmailTemplateRow> {
  const resp = await request.patch(
    `${API_URL}/admin/email-templates/${key}/${locale}`,
    { data: payload },
  );
  if (!resp.ok()) {
    throw new Error(
      `patch template ${key}/${locale} failed: ${resp.status()} ${await resp.text()}`,
    );
  }
  return (await resp.json()) as EmailTemplateRow;
}

/**
 * Override ``users.preferred_language`` to a value the Pydantic
 * ``Language`` enum doesn't allow ("es"). The admin API + /users/me
 * PATCH both validate against the enum, so we drop into the mysql
 * container and run a single UPDATE — same compose-and-exec pattern
 * the docker-log scraping helpers use. Returns the prior value so the
 * caller can restore it on teardown.
 */
function setPreferredLanguageRaw(email: string, locale: string): void {
  const compose = process.env.E2E_COMPOSE_FILES ??
    '-f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.e2e.yml';
  // The SQL contains literal single quotes around the values; the
  // outer ``sh -c '...'`` wrapper would otherwise close on the first
  // inner ``'``. The standard POSIX escape is to replace every ``'``
  // with ``'\''`` (close, literal-escaped quote, re-open).
  const sql = `UPDATE users SET preferred_language='${locale}' WHERE email='${email}';`;
  const sqlEscaped = sql.replaceAll("'", "'\\''");
  execSync(
    `docker compose ${compose} exec -T mysql sh -c ` +
      `'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "${sqlEscaped}"'`,
    { encoding: 'utf-8', cwd: '..' },
  );
}

function uniqueEmail(prefix: string): string {
  const stamp = `${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
  return `${prefix}-${stamp}@example.com`;
}

test.describe('Phase 11 — multi-language email templates', () => {
  test.skip(
    !adminEmail || !adminPassword || !adminTotpSecret,
    'E2E_ADMIN_* env vars not set; run via `make smoke`.',
  );

  test('admin can edit a template variant per locale', async ({ page }) => {
    await loginAsAdmin(page);

    // Snapshot the original NL invite subject/body so we can restore
    // both fields on teardown — the seed migration owns the canonical
    // copy and a sibling spec might assert against it.
    const originalNl = await getEmailTemplate(page.request, 'invite', 'nl');
    const originalEn = await getEmailTemplate(page.request, 'invite', 'en');

    try {
      await page.goto('/admin?tab=emails');

      // Open the invite row's edit modal. The grouped table renders one
      // row per template key; ``getByRole('row')`` then filtering by
      // the monospace ``invite`` cell finds it.
      const inviteRow = page.getByRole('row').filter({ hasText: 'invite' });
      await expect(inviteRow.first()).toBeVisible();
      // The edit button is the only ActionIcon in the row's last cell.
      await inviteRow.first().getByRole('button').click();

      // Modal mounts on the first enabled locale (EN by default).
      // Switch the SegmentedControl to NL; the SegmentedControl is the
      // only one in the modal so finding by role is unambiguous.
      // Mantine SegmentedControl renders ``<label>nl</label>`` with a
      // visually-hidden radio input. Click the visible label scoped
      // to the open modal.
      await page.getByRole('dialog').getByText('nl', { exact: true }).click();

      // Wait for the variant query to settle — the body editor
      // remounts under the new (key, locale) key. Use the Subject
      // text input scoped to the modal; ``toHaveValue`` polls until
      // the field re-renders with the NL data.
      const modal = page.getByRole('dialog');
      const subjectInput = modal.getByLabel(/^Subject$/i);
      await expect(subjectInput).toHaveValue(originalNl.subject);

      const newNlSubject = '[E2E test] Welkom bij Atrium';
      await subjectInput.fill(newNlSubject);

      const savePromise = page.waitForResponse(
        (resp) =>
          resp.url().endsWith('/admin/email-templates/invite/nl') &&
          resp.request().method() === 'PATCH' &&
          resp.ok(),
      );
      await page.getByRole('button', { name: /^Save$|^Opslaan$/ }).click();
      await savePromise;

      // Reload — the modal closes on save; reopening re-fetches.
      await page.reload();
      const reopenRow = page.getByRole('row').filter({ hasText: 'invite' });
      await reopenRow.first().getByRole('button').click();
      // Mantine SegmentedControl renders ``<label>nl</label>`` with a
      // visually-hidden radio input. Click the visible label scoped
      // to the open modal.
      await page.getByRole('dialog').getByText('nl', { exact: true }).click();

      // NL subject is the freshly-saved value.
      const reopenModal = page.getByRole('dialog');
      const reopenSubject = reopenModal.getByLabel(/^Subject$/i);
      await expect(reopenSubject).toHaveValue(newNlSubject);

      // EN subject is unchanged — switch back to verify.
      await reopenModal.getByText('en', { exact: true }).click();
      await expect(reopenSubject).toHaveValue(originalEn.subject);
    } finally {
      // Restore both subject and body so a re-run starts from the
      // seed values. The PATCH endpoint accepts partial updates.
      await patchEmailTemplate(page.request, 'invite', 'nl', {
        subject: originalNl.subject,
        body_html: originalNl.body_html,
      });
    }
  });

  test('email is sent in the recipient registered locale', async ({
    browser,
  }) => {
    // The verify-email send path passes ``locale=lang_value`` derived
    // from the user's signup-time language pick. Open the gate so the
    // /register endpoint exists, register a Dutch user via API (so we
    // don't depend on the UI's locale switcher state), and assert the
    // console log block carries the NL subject.
    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await loginAsAdmin(adminPage);

    const priorAuth = await adminPage.request.get(
      `${API_URL}/admin/app-config`,
    );
    if (!priorAuth.ok()) {
      throw new Error(`admin app-config read failed: ${priorAuth.status()}`);
    }
    const priorAuthBody = (await priorAuth.json()) as {
      auth?: { allow_signup?: boolean };
    };
    const wasOpen = Boolean(priorAuthBody.auth?.allow_signup);

    try {
      if (!wasOpen) {
        await setAuthConfig(adminPage.request, { allow_signup: true });
      }

      const email = uniqueEmail('e2e-i18n-nl');
      const visitorContext = await browser.newContext();
      try {
        const regResp = await visitorContext.request.post(
          `${API_URL}/auth/register`,
          {
            data: {
              email,
              password: 'signup-pw-12345',
              full_name: 'NL Tester',
              language: 'nl',
            },
          },
        );
        expect([200, 201, 204].includes(regResp.status())).toBe(true);

        // Console mail backend lands the message in api stdout — poll
        // until docker logs flush. The seeded NL subject for
        // ``email_verify`` starts with "Bevestig je e-mailadres".
        let entry: { subject: string; body_text: string } | null = null;
        await expect
          .poll(
            () => {
              try {
                entry = readLatestEmailLogEntry('email_verify', email);
                return entry.subject;
              } catch {
                return '';
              }
            },
            {
              message: 'NL email_verify message should land in api logs',
              timeout: 15000,
            },
          )
          .toMatch(/Bevestig je e-mailadres/i);

        // Sanity: the NL body greeting is "Hallo …" (also EN); pin a
        // string the EN seed doesn't carry — "Bevestig je e-mailadres"
        // appears as the link text in the body too.
        expect(entry!.body_text).toMatch(/Bevestig je e-mailadres/i);
      } finally {
        await visitorContext.close();
      }
    } finally {
      if (!wasOpen) {
        await setAuthConfig(adminPage.request, { allow_signup: false });
      }
      await adminContext.close();
    }
  });

  test('falls back to en when locale variant does not exist', async ({
    page,
  }) => {
    // Provision a fresh user, override their preferred_language to
    // ``es`` (no row exists), trigger /auth/forgot-password, and
    // assert the console block carries the EN subject ("Reset your
    // password" or whatever the seed says — match a fragment that
    // cannot appear in the NL/DE/FR translations).
    const user = await loginAsUser(page);

    try {
      setPreferredLanguageRaw(user.email, 'es');

      // ``/auth/forgot-password`` is unauthenticated — make sure the
      // request context isn't carrying the user's cookie when we hit
      // it (the endpoint accepts anyway, but cleaner this way).
      const fp = await page.request.post(
        `${API_URL}/auth/forgot-password`,
        { data: { email: user.email } },
      );
      // fastapi-users returns 202 Accepted; either way the call is
      // fire-and-forget from the user's perspective.
      expect([200, 202, 204].includes(fp.status())).toBe(true);

      let entry: { subject: string; body_text: string } | null = null;
      await expect
        .poll(
          () => {
            try {
              entry = readLatestEmailLogEntry('password_reset', user.email);
              return entry.subject;
            } catch {
              return '';
            }
          },
          {
            message: 'password_reset message should land in api logs',
            timeout: 15000,
          },
        )
        // The seeded EN subject for ``password_reset`` reads
        // "Reset your password". Match a phrase the NL/DE/FR seeds
        // do NOT contain — "your password" appears only in EN
        // ("Stel je wachtwoord", "Setze dein Passwort", "Reinitialiser
        // votre mot de passe" all avoid the literal English phrase).
        .toMatch(/your password/i);

      // Body should also be in English — pin a phrase unique to the
      // EN seed body ("you can ignore this email") that none of the
      // translation seeds contain in those exact words.
      expect(entry!.body_text.toLowerCase()).toContain('ignore');
    } finally {
      // Restore the user to a known locale so any subsequent spec
      // running against the same DB starts clean.
      setPreferredLanguageRaw(user.email, 'en');
    }
  });

  test('non-admin does not see the Email templates tab', async ({ page }) => {
    await loginAsUser(page);
    await page.goto('/admin');

    // Wait for the Users tab — universal — so we know the page rendered
    // before asserting the Email templates tab is absent.
    await expect(
      page.getByRole('tab', { name: /Users|Gebruikers/i }),
    ).toBeVisible();
    await expect(
      page.getByRole('tab', { name: /Email templates|E-mailsjablonen/i }),
    ).toHaveCount(0);

    // Direct-URL access should fall through to the default tab — the
    // AdminPage validates ``?tab=emails`` against the user's perms.
    await page.goto('/admin?tab=emails');
    await expect(
      page.getByRole('tab', { name: /Users|Gebruikers/i }),
    ).toHaveAttribute('aria-selected', 'true');
  });
});
