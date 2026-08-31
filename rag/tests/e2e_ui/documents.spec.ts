/**
 * Documents UI E2E — document upload, search filter, and delete.
 *
 * Backend has RAG_E2E_FAKES=1; uploads run against real Milvus Lite + the
 * cached local embedding model, but every on-disk path is redirected to a
 * process-level temp dir (see tests/e2e_ui/_fakes.py), so the real
 * ./milvus_data.db / ./data/ is never touched.
 *
 * Uses setInputFiles on the (hidden) file input rather than the OS picker.
 */
import { test, expect } from "@playwright/test";
import { screenshot, autoConfirmDialog } from "./helpers";
import * as path from "path";

const SHOT_DIR = "documents";
const SAMPLE = path.resolve(__dirname, "fixtures", "sample.md");

test.describe("Documents UI", () => {
  test("uploads a markdown file and it appears in the list", async ({ page }) => {
    await page.goto("/documents");
    await expect(page.getByTestId("upload-area")).toBeVisible();
    await screenshot(page, SHOT_DIR, "empty");

    // Upload via the hidden file input (not the OS picker).
    await page.getByTestId("file-input").setInputFiles(SAMPLE);

    // The document card should appear. Status may be 'processing' briefly then
    // 'indexed'/'processed'; just assert the card with the filename renders.
    await expect(
      page.locator("[data-testid='doc-card'] .doc-name").filter({ hasText: "sample.md" })
    ).toBeVisible({ timeout: 60_000 });
    await screenshot(page, SHOT_DIR, "uploaded");
  });

  test("search filter narrows the document list", async ({ page }) => {
    await page.goto("/documents");
    // Ensure at least one doc exists (upload if list is empty).
    if (await page.getByTestId("doc-empty").count()) {
      await page.getByTestId("file-input").setInputFiles(SAMPLE);
      await expect(page.getByTestId("doc-card")).toBeVisible({ timeout: 60_000 });
    }

    const search = page.getByTestId("doc-search");
    await search.fill("nonexistent-zzz");
    await expect(page.getByTestId("doc-empty")).toBeVisible();
    await screenshot(page, SHOT_DIR, "search-empty");

    await search.fill("sample");
    await expect(page.getByTestId("doc-card")).toBeVisible();
    await screenshot(page, SHOT_DIR, "search-match");
  });

  test("delete removes the document", async ({ page }) => {
    await page.goto("/documents");
    // Seed a doc to delete.
    if (!(await page.getByTestId("doc-card").count())) {
      await page.getByTestId("file-input").setInputFiles(SAMPLE);
      await expect(page.getByTestId("doc-card")).toBeVisible({ timeout: 60_000 });
    }

    // The list endpoint caps at limit=20, but the registry total is uncapped.
    // Across test runs the shared backend accumulates uploads, so the visible
    // doc-card count can sit at the 20-cap and never visibly decrease after a
    // single delete. Assert against the registry total (reflects the real
    // delete) instead of the capped card count.
    const beforeTotal = (await (await page.request.get("/api/documents")).json()).total;

    const stop = autoConfirmDialog(page, true);
    await page.getByTestId("doc-delete").first().click();
    stop();

    await expect.poll(
      async () => (await (await page.request.get("/api/documents")).json()).total,
      { timeout: 30_000 }
    ).toBe(beforeTotal - 1);
    await screenshot(page, SHOT_DIR, "after-delete");
  });
});
