// Playwright config (F25) — browser E2E for the Vue SPA.
//
// Tests live in /tests/e2e_ui (project root). The webServer block starts the
// backend (which serves the built web/dist SPA via FastAPI) on :8000. The CI
// job builds web/dist first, then runs `npx playwright test`.
//
// SSE streaming is exercised via page.waitForResponse / text assertions rather
// than byte-boundary checks (which are flaky); see tests/e2e_ui/chat.spec.ts.
import { defineConfig, devices } from "@playwright/test";

const BACKEND = process.env.E2E_BACKEND_URL || "http://127.0.0.1:8000";

export default defineConfig({
  testDir: "../tests/e2e_ui",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: BACKEND,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: {
    // Build web/dist first (npm run build), then start the backend. The
    // RAG_E2E_FAKES=1 env triggers deterministic fake injection INTO this
    // uvicorn subprocess (see tests/e2e_ui/_fakes.py + api/main.py hook) so
    // browser E2E needs no Ollama/Milvus and stays hermetic. PYTEST_RUN=1 only
    // skips the F05 production-config startup guard; it does NOT inject fakes.
    // No DOMAIN_PROFILE override: the e2e_ui fakes/fixtures (sample.md, canned
    // answers) are domain-neutral, matching the platform's default general
    // (domain-agnostic) profile.
    command: process.env.E2E_NO_WEBSERVER
      ? "echo 'using externally-started backend'"
      : `cd .. && PYTEST_RUN=1 RAG_E2E_FAKES=1 uv run --frozen --no-sync uvicorn api.main:app --host 127.0.0.1 --port 8000`,
    url: BACKEND,
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
