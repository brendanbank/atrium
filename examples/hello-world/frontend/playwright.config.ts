/**
 * Playwright config for the Hello World smoke spec.
 *
 * Lives inside ``examples/hello-world/frontend`` so Playwright's
 * module resolver can find both the dev deps (Playwright, otplib)
 * and the spec's helpers from a single ``node_modules`` tree.
 * Pointed at the dev SPA on :5173 by default; override with
 * E2E_BASE_URL for a different port.
 */
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests-e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
});
