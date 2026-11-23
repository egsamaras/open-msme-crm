import { defineConfig, devices } from '@playwright/test'

// End-to-end tests drive the real app: a fresh database (reset, migrated, seeded), the real
// FastAPI backend in mock LLM mode and the Vite frontend, on ports that don't clash with dev.
const API_PORT = 8100
const WEB_PORT = 5180
const DB = process.env.E2E_DATABASE_URL ?? 'postgresql+asyncpg://crm:crm@localhost:5432/crm_e2e'
const backendEnv = {
  DATABASE_URL: DB,
  CHECKPOINT_DATABASE_URL: DB.replace('+asyncpg', ''),
  ENVIRONMENT: 'development',
  LLM_PROVIDER: 'mock',
  CORS_ORIGINS: `["http://localhost:${WEB_PORT}"]`,
}

export default defineConfig({
  testDir: 'e2e',
  // Flows share one database and build on the seed, so they run one at a time, in file order.
  workers: 1,
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: 'retain-on-failure',
    ...devices['Desktop Chrome'],
    viewport: { width: 1440, height: 900 },
  },
  projects: [
    { name: 'flows', testIgnore: /screenshots\.spec\.ts/ },
    { name: 'screenshots', testMatch: /screenshots\.spec\.ts/ },
  ],
  webServer: [
    {
      command: `uv run python -m app.db.reset --yes && uv run uvicorn app.main:app --port ${API_PORT}`,
      cwd: '../backend',
      url: `http://localhost:${API_PORT}/api/health`,
      env: backendEnv,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `npx vite --port ${WEB_PORT} --strictPort`,
      url: `http://localhost:${WEB_PORT}`,
      env: { API_URL: `http://localhost:${API_PORT}` },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
