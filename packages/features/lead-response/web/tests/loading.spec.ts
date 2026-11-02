import { test, expect } from "@playwright/test";
import { hold, noHorizontalScroll, shot, tid, URL_SETTINGS, useWorkspace } from "./helpers";

// While the settings are being read the page shows a skeleton shaped like it, and the real page replaces it. The read
// is server to server, so the browser cannot delay it; instead the seed holds a lock on the settings table for a few
// seconds (released by the seed itself, always), and the API's read waits for it.
test.setTimeout(120_000);

test.describe("the loading state", () => {
  const workspace = useWorkspace({ scenario: "saved" });

  test("a skeleton shows while the read waits, then the real page replaces it", async ({ page }) => {
    const lock = await hold(workspace(), 8);
    try {
      await page.goto(URL_SETTINGS, { waitUntil: "commit" });
      const region = page.getByTestId("settings-loading");
      await expect(region).toBeVisible({ timeout: 15_000 });
      await expect(region).toHaveAttribute("role", "status");
      await expect(region).toHaveAttribute("aria-busy", "true");
      await expect(region.getByText("Loading lead response settings")).toBeAttached();
      await expect(page.getByTestId("settings-skeleton")).toBeVisible();
      await expect(page.getByTestId("settings-form")).toHaveCount(0);
      await shot(page, "loading-skeleton-" + page.viewportSize()!.width);
      await noHorizontalScroll(page);
    } finally {
      lock.kill();
    }
    await expect(tid(page, "settings-form")).toHaveAttribute("data-ready", "true", { timeout: 40_000 });
    await expect(page.getByTestId("settings-loading")).toHaveCount(0);
    await expect(tid(page, "field-holding")).toHaveValue("20");
  });

  test("with reduced motion the skeleton does not pulse", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const lock = await hold(workspace(), 8);
    try {
      await page.goto(URL_SETTINGS, { waitUntil: "commit" });
      const bar = page.getByTestId("settings-skeleton").locator('[aria-hidden="true"]').first();
      await expect(bar).toBeVisible({ timeout: 15_000 });
      await expect(bar).toHaveCSS("animation-name", "none");
    } finally {
      lock.kill();
    }
    await expect(tid(page, "settings-form")).toHaveAttribute("data-ready", "true", { timeout: 40_000 });
  });

  test("the skeleton does not scroll sideways on a phone", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 740 });
    const lock = await hold(workspace(), 8);
    try {
      await page.goto(URL_SETTINGS, { waitUntil: "commit" });
      await expect(page.getByTestId("settings-skeleton")).toBeVisible({ timeout: 15_000 });
      await noHorizontalScroll(page);
      await shot(page, "loading-skeleton-360");
    } finally {
      lock.kill();
    }
    await expect(tid(page, "settings-form")).toHaveAttribute("data-ready", "true", { timeout: 40_000 });
  });
});
