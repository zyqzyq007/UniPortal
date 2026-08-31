/**
 * Admin UI E2E — health grid, circuit breakers, degradation mode, metrics.
 *
 * Backend has RAG_E2E_FAKES=1. These are read-mostly assertions plus the
 * degradation-mode switch (a row of buttons, not a <select>).
 */
import { test, expect } from "@playwright/test";
import { screenshot } from "./helpers";

const SHOT_DIR = "admin";

/**
 * Mocked /api/admin/health payload for the reranker-status-display tests.
 * reranker is "ready" (model cached but not resident in memory) — the exact
 * transient state that previously rendered a red ✗ while the top badge said
 * "正常". See docs/specs/reranker-status-display/.
 */
const HEALTH_RERANKER_READY = {
  status: "healthy",
  services: {
    llm: { status: "healthy", circuit: "closed", stats: {} },
    retriever: { status: "healthy", circuit: "closed", stats: {} },
    milvus: { status: "healthy", details: {} },
    reranker: {
      status: "ready",
      details: { loaded: false, cached: true, load_error: null },
    },
  },
};

test.describe("Admin UI", () => {
  test("all four sections render", async ({ page }) => {
    await page.goto("/admin");
    await expect(page.getByTestId("admin-section-health")).toBeVisible();
    await expect(page.getByTestId("admin-section-circuits")).toBeVisible();
    await expect(page.getByTestId("admin-section-degradation")).toBeVisible();
    await expect(page.getByTestId("admin-section-metrics")).toBeVisible();
    await screenshot(page, SHOT_DIR, "overview");
  });

  test("degradation mode buttons switch active state", async ({ page }) => {
    await page.goto("/admin");
    // Default mode is 'full' (active).
    await expect(page.getByTestId("degradation-mode-full")).toHaveClass(/active/);

    await page.getByTestId("degradation-mode-cached").click();
    await expect(page.getByTestId("degradation-mode-cached")).toHaveClass(/active/);
    await expect(page.getByTestId("degradation-mode-full")).not.toHaveClass(/active/);
    await screenshot(page, SHOT_DIR, "mode-cached");

    // Restore full mode.
    await page.getByTestId("degradation-mode-full").click();
    await expect(page.getByTestId("degradation-mode-full")).toHaveClass(/active/);
  });

  test("reranker 'ready' state renders neutral, not failure cross", async ({ page }) => {
    // [REQ-RS-001/002/003/004] A reranker in the 'ready' transient state (model
    // cached but not yet resident in memory) must render a neutral "就绪" card,
    // NOT the red ✗ cross. The top badge must stay "正常" (no contradiction).
    // See docs/specs/reranker-status-display/requirements.md.
    await page.route("**/api/admin/health", async (route) => {
      await route.fulfill({ json: HEALTH_RERANKER_READY });
    });

    await page.goto("/admin");
    await expect(page.getByTestId("admin-section-health")).toBeVisible();

    // Top badge: "ready" must not lower the overall status.
    await expect(page.locator(".overall-status")).toHaveText(/正常/);
    await expect(page.locator(".overall-status")).toHaveClass(/healthy/);

    // The reranker card: neutral class + Chinese label + localized name.
    const rerankerCard = page.locator(".health-card.ready");
    await expect(rerankerCard).toBeVisible();
    await expect(rerankerCard.locator(".service-name")).toHaveText(/重排模型/);
    await expect(rerankerCard.locator(".service-status")).toHaveText(/就绪/);

    // MUST NOT carry the failure (unhealthy) class that paints the red ✗.
    await expect(rerankerCard).not.toHaveClass(/unhealthy/);

    await screenshot(page, SHOT_DIR, "reranker-ready-neutral");
  });
});
