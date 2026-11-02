import { test, expect, type Page } from "@playwright/test";
import { noHorizontalScroll, openSettings, shot, tid, useWorkspace } from "./helpers";

// Next also streams a hidden, server-rendered copy of the page, so a shell element can exist twice in the document.
// Look only at the copy a person can see.
const shell = (page: Page, id: string) => page.locator(`[data-testid="${id}"]:visible`);

async function insideViewport(page: Page, ids: string[]) {
  const width = page.viewportSize()!.width;
  for (const id of ids) {
    const box = await tid(page, id).boundingBox();
    expect(box, id).not.toBeNull();
    expect(box!.x, `${id} starts left of the screen`).toBeGreaterThanOrEqual(-1);
    expect(box!.x + box!.width, `${id} runs off the right edge`).toBeLessThanOrEqual(width + 1);
  }
}

test.describe("screen sizes", () => {
  useWorkspace({ scenario: "saved" });

  test("1280 px: the sidebar is beside the page, there is no menu button, nothing scrolls sideways", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await openSettings(page);
    await expect(shell(page, "menu-button")).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Settings", exact: true })).toBeVisible();
    await expect(shell(page, "profile")).toHaveCount(1);
    await noHorizontalScroll(page);
    await expect(tid(page, "save-bar")).toBeVisible();
    await shot(page, "size-1280-saved");
    await tid(page, "field-holding").fill("4");
    await tid(page, "save").click();
    await shot(page, "size-1280-errors");
  });

  test("768 px: still the wide layout (the menu turns into a bar at 700 px and narrower), nothing scrolls sideways", async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    await openSettings(page);
    await expect(shell(page, "menu-button")).toHaveCount(0);
    await noHorizontalScroll(page);
    await insideViewport(page, ["field-ack", "field-holding", "field-sla", "field-role", "save-bar", "start-mon-0", "quiet-start"]);
    await shot(page, "size-768-saved");
  });

  test("360 px: a top bar with a Menu button, every control inside the screen, no sideways scroll", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 740 });
    await openSettings(page);
    await expect(shell(page, "menu-button")).toHaveCount(1);
    await expect(shell(page, "menu-panel")).toHaveCount(0);
    await noHorizontalScroll(page);
    await insideViewport(page, ["field-ack", "field-holding", "field-sla", "field-role", "save-bar", "start-fri-0", "end-fri-1", "remove-fri-0", "add-fri", "quiet-start", "quiet-end"]);
    for (const id of ["save", "discard", "reset"]) {
      const box = await tid(page, id).boundingBox();
      expect(box!.height, `${id} is too small to tap`).toBeGreaterThanOrEqual(40);
    }
    await shot(page, "size-360-saved");
    await tid(page, "field-holding").fill("4");
    await tid(page, "save").click();
    await noHorizontalScroll(page);
    await shot(page, "size-360-errors");
  });

  test("360 px: the menu opens, focus goes to the first link in its navigation, Escape closes it and returns focus to the button", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 740 });
    await openSettings(page);
    const button = shell(page, "menu-button");
    await expect(button).toHaveAttribute("aria-expanded", "false");
    await button.focus();
    await page.keyboard.press("Enter");
    await expect(button).toHaveAttribute("aria-expanded", "true");
    await expect(shell(page, "menu-panel")).toHaveCount(1);
    await expect(page.getByRole("navigation", { name: "Lead response sections" }).getByRole("link", { name: "Settings" })).toBeFocused();
    await noHorizontalScroll(page);
    await shot(page, "size-360-menu-open");
    await page.keyboard.press("Escape");
    await expect(button).toHaveAttribute("aria-expanded", "false");
    await expect(shell(page, "menu-panel")).toHaveCount(0);
    await expect(button).toBeFocused();
  });
});
