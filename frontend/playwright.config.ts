import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright E2E Test Configuration
 *
 * Run with: npm run test:e2e
 *
 * Setup/Teardown:
 *   - globalSetup: Starts daemon on port 5997
 *   - webServer: Starts frontend dev server on port 8792
 *   - globalTeardown: Stops daemon
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'list',
  timeout: 30000,

  // Start daemon before all tests, stop after
  globalSetup: './e2e/global-setup.ts',
  globalTeardown: './e2e/global-teardown.ts',

  use: {
    baseURL: 'http://localhost:8792',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  // Start frontend dev server before tests
  webServer: {
    command: 'pnpm dev',
    url: 'http://localhost:8792',
    reuseExistingServer: !process.env.CI,
    timeout: 30000,
  },
})
