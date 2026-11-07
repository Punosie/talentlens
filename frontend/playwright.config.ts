import { defineConfig, devices } from '@playwright/test'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// One throwaway fixture folder per run; shared with the specs through the environment.
const root = process.env.TL_E2E_ROOT ?? path.join(os.tmpdir(), `talentlens-e2e-${process.pid}`)
process.env.TL_E2E_ROOT = root
const port = Number(process.env.TL_E2E_PORT ?? 8799)
const repo = fileURLToPath(new URL('..', import.meta.url))

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false, // specs share one server and fixture folder
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `uv run python backend/tests/e2e_server.py --root "${root}" --port ${port}`,
    cwd: repo,
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
})
