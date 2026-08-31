import { expect, test } from "@playwright/test";
import { screenshot } from "./helpers";

test.describe("prefixed production deployment", () => {
  test.skip(process.env.E2E_PREFIX_MODE !== "1", "requires the Nginx /rag harness");

  test("keeps SPA, API and SSE traffic under /rag", async ({ page }) => {
    const apiPaths: string[] = [];
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (url.pathname.includes("/api/")) apiPaths.push(url.pathname);
    });

    await page.goto("./");
    await expect(page).toHaveURL(/\/rag\/$/);
    await expect(page.getByTestId("welcome")).toBeVisible();

    const response = page.waitForResponse((item) => {
      return new URL(item.url()).pathname === "/rag/api/chat/stream";
    });
    await page.getByTestId("chat-input").fill("git 合并冲突如何解决？");
    await page.getByTestId("chat-input").press("Enter");
    expect((await response).ok()).toBe(true);
    await expect(page.locator("[data-testid='message'].assistant").last()).toContainText(
      /合并|冲突|Git|提交/,
      { timeout: 30_000 },
    );

    await page.goto("./documents");
    await expect(page.getByTestId("upload-area")).toBeVisible();
    await page.goto("./sessions");
    await expect(page.getByTestId("session-new")).toBeVisible();
    await page.goto("./admin");
    await expect(page.getByTestId("admin-section-health")).toBeVisible();

    expect(apiPaths.length).toBeGreaterThan(0);
    expect(apiPaths.every((path) => path.startsWith("/rag/api/"))).toBe(true);
    await screenshot(page, "deployment", "prefix-rag");
  });
});
