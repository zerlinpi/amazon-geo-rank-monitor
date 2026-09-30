import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  retries: 0,
  timeout: 45000,
  expect: { timeout: 10000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:4173',
    viewport: { width: 1440, height: 1000 },
    // Runner-installed Chrome is supported when browser downloads are unavailable.
    channel: process.env.E2E_BROWSER_CHANNEL || undefined,
    launchOptions: { executablePath: process.env.E2E_BROWSER_PATH || undefined },
    trace: 'off', // Traces can contain session cookies; use redacted assertions instead.
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'utc', use: { timezoneId: 'UTC' } },
    { name: 'new_york', use: { timezoneId: 'America/New_York' } },
    { name: 'singapore', use: { timezoneId: 'Asia/Singapore' } },
  ],
  webServer: [
    {
      command: `${process.env.E2E_PYTHON || '../.venv/bin/python'} -m uvicorn e2e_server:app --host 127.0.0.1 --port 8000 --no-access-log --log-level warning`,
      env: { PYTHONPATH: '../backend/src:../backend/tests' },
      url: 'http://127.0.0.1:8000/ready', timeout: 60000,
    },
    { command: 'npm run preview', url: 'http://127.0.0.1:4173', timeout: 30000 },
  ],
})
