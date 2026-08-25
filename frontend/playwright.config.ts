import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 30000,
  expect: {
    timeout: 5000,
  },
  retries: 0,
  workers: process.env.CI ? 1 : undefined,

  use: {
    headless: true,
    viewport: { width: 1440, height: 900 },
    baseURL: 'http://localhost:3000',
    trace: 'on-first-retry',
  },

  // Test match pattern
  // projects: [...],
});