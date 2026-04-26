import { defineConfig } from '@playwright/test';

/**
 * Smoke-only E2E. Expects the app to already be running at
 * http://localhost:5173 (backed by the dev compose stack).
 *
 * CI seeds an owner via the backend CLI before the tests run; see
 * .github/workflows/ci.yml.
 */
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
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
  ],
});
