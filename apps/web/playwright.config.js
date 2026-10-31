import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for PRD S9.5 e2e tests.
 * 
 * Tests run against a local API server (must be running separately).
 * Use: npx playwright test
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false, // Sequential for now (shared database state)
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1, // Single worker to avoid database conflicts
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:8000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  // Don't start the API server - it must be running separately
  // webServer: undefined,
});
