// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { execSync } from 'child_process';

import { expect, test } from '@playwright/test';

import { loginAsSuperAdmin } from './helpers';

/**
 * EmailOutboxAdmin (`/admin/outbox`) coverage. Atrium's platform code
 * doesn't itself enqueue outbox rows — that's a host-side API
 * (``enqueue_and_log``). To exercise the drain UI we insert a row
 * directly through the mysql container, mirroring the pattern used
 * elsewhere when the public API can't reach the desired state.
 */

const adminEmail = process.env.E2E_ADMIN_EMAIL;
const adminPassword = process.env.E2E_ADMIN_PASSWORD;
const adminTotpSecret = process.env.E2E_ADMIN_TOTP_SECRET;

const haveSmokeEnv = Boolean(adminEmail && adminPassword && adminTotpSecret);

test.skip(
  !haveSmokeEnv,
  'E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD / E2E_ADMIN_TOTP_SECRET must be set (run via `make smoke`).',
);

function mysqlExec(sql: string): string {
  const compose = process.env.E2E_COMPOSE_FILES ??
    '-f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.e2e.yml';
  const sqlEscaped = sql.replaceAll("'", "'\\''");
  return execSync(
    `docker compose ${compose} exec -T mysql sh -c ` +
      `'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -N -e "${sqlEscaped}"'`,
    { encoding: 'utf-8', cwd: '..' },
  );
}

test.describe('Email outbox admin', () => {
  test.describe.configure({ mode: 'serial' });
  test.describe.configure({ timeout: 10_000 });

  test('admin can drain a pending outbox row', async ({ page }) => {
    const recipient = `outbox-${Date.now()}@example.com`;
    // Seed a pending row pointed at a known template.
    // ``next_attempt_at`` in the past ensures the worker would also
    // pick it up; we drain manually via the admin UI before that.
    // ``email_otp_code`` template needs ``user_name`` + ``code`` in
     // its context — render-fails without both.
    mysqlExec(
      `INSERT INTO email_outbox
       (status, template, locale, to_addr, context, attempts, next_attempt_at, last_error, entity_type, entity_id)
       VALUES ('pending', 'email_otp_code', 'en', '${recipient}',
         JSON_OBJECT('code', '123456', 'user_name', 'Outbox E2E'),
         0, DATE_SUB(NOW(), INTERVAL 1 SECOND), NULL, NULL, NULL);`,
    );

    try {
      await loginAsSuperAdmin(page);
      await page.goto('/admin/outbox');

      // Two "Email outbox" headings render (the SectionPage's h2 outer
       // title and the component's own h3) — anchor on the table header
       // instead, which is unique to the loaded component.
      await expect(
        page.getByRole('columnheader', { name: /^Recipient$/i }),
      ).toBeVisible();

      // Default filter is "Pending"; the seeded row should appear.
      const row = page.locator('tbody tr', { hasText: recipient });
      await expect(row).toBeVisible();
      await expect(row.getByText(/^pending$/i)).toBeVisible();

      // Click the drain button (label "Send now"). The console mail
      // backend always succeeds, so the row flips to ``sent`` and
      // disappears from the default "Pending" view.
      await row.getByRole('button', { name: /^Send now$/i }).click();
      await expect(
        page.locator('tbody tr', { hasText: recipient }),
      ).toHaveCount(0);

      // Switching the filter to ``Sent`` surfaces the row in its
      // terminal state. Mantine's SegmentedControl uses hidden radio
      // inputs — click the visible label instead.
      await page.locator('label').filter({ hasText: /^Sent$/ }).click();
      const sentRow = page.locator('tbody tr', { hasText: recipient });
      await expect(sentRow).toBeVisible();
      await expect(sentRow.getByText(/^sent$/i)).toBeVisible();
    } finally {
      mysqlExec(`DELETE FROM email_outbox WHERE to_addr = '${recipient}';`);
    }
  });
});
