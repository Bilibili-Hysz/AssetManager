import { existsSync } from 'node:fs';
import { defineConfig } from '@playwright/test';

const localChromiumExecutable = 'C:\\Users\\86177\\AppData\\Local\\ms-playwright\\chromium-1228\\chrome-win64\\chrome.exe';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: 0,
  use: {
    baseURL: 'http://localhost:4173',
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    launchOptions: existsSync(localChromiumExecutable)
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
