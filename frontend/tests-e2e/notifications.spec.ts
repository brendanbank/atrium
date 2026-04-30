// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { execSync } from 'child_process';

import { expect, test } from '@playwright/test';

import { API_URL, loginAsSuperAdmin } from './helpers';

/**
 * NotificationsBell coverage. Atrium's bell + dropdown reads from
 * /api/notifications. Atrium's platform code doesn't itself emit
 * notifications (host apps own the kinds), so this spec inserts a
 * row directly via mysql, mirroring the email-outbox pattern.
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

test.describe('Notifications bell', () => {
  test.describe.configure({ mode: 'serial' });
  test.describe.configure({ timeout: 15_000 });

  test('bell renders the unread count and lists notifications', async ({
    page,
  }) => {
    await loginAsSuperAdmin(page);

    // Resolve the smoke admin's user id via the API so we can insert
    // notifications targeting them. /users/me returns it.
    const meResp = await page.request.get(`${API_URL}/users/me`);
    const me = (await meResp.json()) as { id: number };
    const tag = `e2e-notif-${Date.now()}`;

    try {
      // Wipe any pre-existing notifications for the smoke admin so the
      // unread count is deterministic. Other specs may have created
      // some via host-side flows.
      mysqlExec(`DELETE FROM notifications WHERE user_id = ${me.id};`);

      // Reload so the bell's TanStack queries pick up the empty state.
      await page.goto('/');
      const bell = page.getByRole('button', { name: /notifications/i }).first();
      await expect(bell).toBeVisible();

      // Empty state — open the popover, assert the empty copy.
      await bell.click();
      await expect(page.getByText(/no notifications yet/i)).toBeVisible();
      await page.keyboard.press('Escape');

      // Insert two unread notifications + one already-read.
      mysqlExec(
        `INSERT INTO notifications (user_id, kind, payload, read_at)
         VALUES
         (${me.id}, '${tag}_unread1', JSON_OBJECT('msg', 'one'), NULL),
         (${me.id}, '${tag}_unread2', JSON_OBJECT('msg', 'two'), NULL),
         (${me.id}, '${tag}_read', JSON_OBJECT('msg', 'three'), NOW());`,
      );

      // Reload so the bell pulls the freshly-inserted rows.
      await page.reload();
      await expect(bell).toBeVisible();

      // Open and assert both unread rows show up. ``new`` badge marks
      // each unread item.
      await bell.click();
      await expect(page.getByText(`${tag}_unread1`)).toBeVisible();
      await expect(page.getByText(`${tag}_unread2`)).toBeVisible();
      await expect(page.getByText(`${tag}_read`)).toBeVisible();

      // ``Mark all read`` button only renders when unread > 0.
      await page.getByRole('button', { name: /mark all read/i }).click();

      // The button disappears once unread hits 0.
      await expect(
        page.getByRole('button', { name: /mark all read/i }),
      ).toHaveCount(0);
    } finally {
      mysqlExec(
        `DELETE FROM notifications WHERE user_id = ${me.id} AND kind LIKE '${tag}%';`,
      );
    }
  });
});
