// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { defineConfig } from '@playwright/test';

/**
 * Two projects:
 *   * ``smoke`` — four critical golden paths (login, invite, signup,
 *     logout). Runs on every PR (~15 s) to prove the full stack
 *     boots and the auth + browser plumbing works.
 *   * ``extended`` — admin-config UI surfaces (branding, i18n,
 *     captcha, email-templates, etc). Backend pytest already covers
 *     the same flows; these specs exist as a UI regression net but
 *     are too noisy to gate every PR on. Run via
 *     ``pnpm playwright test --project=extended`` or
 *     ``make smoke-extended`` before risky frontend changes.
 *
 * No ``--project`` flag = both projects = full suite (the previous
 * default behaviour). CI uses ``--project=smoke`` explicitly.
 *
 * Expects the app to already be running at http://localhost:5173
 * (backed by the dev compose stack). CI seeds the smoke admins via
 * the backend CLI before the tests run; see .github/workflows/ci.yml.
 */
const SMOKE_SPECS = [
  '**/smoke.spec.ts',
  '**/invite-flow.spec.ts',
  '**/signup.spec.ts',
  '**/logout.spec.ts',
];

export default defineConfig({
  testDir: './tests-e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'smoke',
      use: { browserName: 'chromium' },
      testMatch: SMOKE_SPECS,
    },
    {
      name: 'extended',
      use: { browserName: 'chromium' },
      testIgnore: SMOKE_SPECS,
    },
  ],
});
