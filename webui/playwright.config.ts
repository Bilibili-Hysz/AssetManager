import { existsSync } from 'node:fs';
import { defineConfig } from '@playwright/test';

// Optional machine-local browser shortcut: point PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
// at a pre-installed Chrome for Windows to skip Playwright's own download.
const localChromiumExecutable = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: 0,
  use: {
    baseURL: 'http://localhost:4173',
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    launchOptions: localChromiumExecutable && existsSync(localChromiumExecutable)
      ? { executablePath: localChromiumExecutable }
      : undefined,
  },
  webServer: {
    command: 'npm run preview -- --host 127.0.0.1 --port 4173',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
  ],
});
