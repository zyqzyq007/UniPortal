/**
 * Shared Playwright helpers for browser E2E.
 */
import type { Page } from "@playwright/test";
import * as path from "path";

const SCREENSHOTS_ROOT = path.resolve(__dirname, "screenshots");

/**
 * Capture a full-page screenshot into tests/e2e_ui/screenshots/<area>/<name>.png.
 * Mirrors the screenshot discipline in web/AGENTS.md §3: every key interaction
 * node is captured so a reviewer can verify the UI rendered correctly.
 */
export async function screenshot(page: Page, area: string, name: string): Promise<void> {
  await page.waitForFunction(() => {
    const transitioning = document.querySelector(
      ".fade-enter-active, .fade-leave-active, .slide-enter-active, .slide-leave-active",
    );
    const messages = Array.from(document.querySelectorAll(".message"));
    return !transitioning && messages.every((message) => {
      return Number.parseFloat(getComputedStyle(message).opacity) >= 0.99;
    });
  });
  await page.addStyleTag({
    content: `
      *, *::before, *::after {
        animation: none !important;
        transition: none !important;
        caret-color: transparent !important;
      }
    `,
  });
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  }));
  await page.screenshot({
    path: path.join(SCREENSHOTS_ROOT, area, `${name}.png`),
    fullPage: true,
  });
}

/**
 * Accept any native confirm()/alert() dialog (used by delete flows). Returns a
 * cleanup function. Pass `false` to dismiss instead.
 *
 * Note: Playwright's Dialog.accept() takes an optional promptText STRING (for
 * prompt() dialogs only), NOT a boolean. For confirm()/alert() we must call
 * accept() with no argument and dismiss() to reject — passing `true` raises
 * "promptText: expected string, got boolean" and the click hangs.
 */
export function autoConfirmDialog(page: Page, accept = true): () => void {
  const handler = (dialog: import("@playwright/test").Dialog) => {
    if (accept) {
      void dialog.accept();
    } else {
      void dialog.dismiss();
    }
  };
  page.on("dialog", handler);
  return () => page.off("dialog", handler);
}
