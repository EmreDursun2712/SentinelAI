import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright end-to-end config.
 *
 * E2E exercises the *real* stack: a running backend (with a trained model + DB)
 * and the built frontend. Point PLAYWRIGHT_BASE_URL at a running frontend, or
 * let Playwright start `vite preview` for you (the backend must already be up at
 * VITE_API_BASE_URL). See e2e/README.md.
 */
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:4173";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  // Generous timeouts: against the compose Vite dev server, the first render of
  // each route compiles on demand, which is slow on a cold CI runner.
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // Start the built frontend unless an external base URL is provided. The backend
  // is expected to be reachable separately (compose stack / dev server).
  webServer: process.env.PLAYWRIGHT_BASE_URL
    ? undefined
    : {
        command: "npm run preview -- --port 4173 --strictPort",
        url: BASE_URL,
        timeout: 120_000,
        reuseExistingServer: !process.env.CI,
      },
});
