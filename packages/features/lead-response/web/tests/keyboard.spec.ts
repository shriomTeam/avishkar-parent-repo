import { test, expect } from "@playwright/test";
import { openSettings, tabTo, tid, useWorkspace } from "./helpers";

test.describe("keyboard only", () => {
  useWorkspace({ scenario: "standard" });

  test("every control can be reached and used without a mouse, through to a saved change", async ({ page }) => {
    await openSettings(page);
    await page.locator("body").click({ position: { x: 1, y: 1 } }); // the one mouse use: put the cursor on the page, not on a control
    await page.keyboard.press("Control+Home");
    await tabTo(page, "field-ack");
    await page.keyboard.press("Control+A");
    await page.keyboard.type("Keyboard wording for the instant reply.");
    await tabTo(page, "field-holding");
    await page.keyboard.press("Control+A");
    await page.keyboard.type("25");
    await tabTo(page, "field-sla");
    await page.keyboard.press("Control+A");
    await page.keyboard.type("70");
    await tabTo(page, "field-role");
    await page.keyboard.type("Owner");
    await tabTo(page, "open-mon");
    await page.keyboard.press("Space");
    await tabTo(page, "add-mon");
    await page.keyboard.press("Enter");
    await expect(tid(page, "window-mon-1")).toBeVisible();
    await tabTo(page, "remove-mon-1");
    await page.keyboard.press("Enter"); // take the new range away again, by keyboard
    await expect(tid(page, "window-mon-1")).toHaveCount(0);
    await tabTo(page, "quiet-on");
    await page.keyboard.press("Space");
    await expect(tid(page, "quiet-start")).toBeVisible();
    await tabTo(page, "save");
    await page.keyboard.press("Enter");
    await expect(tid(page, "saved-notice")).toContainText("Saved (version 1).");
    await page.reload();
    await expect(tid(page, "settings-form")).toHaveAttribute("data-ready", "true");
    await expect(tid(page, "field-ack")).toHaveValue("Keyboard wording for the instant reply.");
    await expect(tid(page, "field-holding")).toHaveValue("25");
    await expect(tid(page, "field-sla")).toHaveValue("70");
    await expect(tid(page, "field-role")).toHaveValue("owner");
    await expect(tid(page, "open-mon")).toBeChecked();
    await expect(tid(page, "quiet-on")).toBeChecked();
  });

  test("whatever has focus shows a thick dark outline, buttons included", async ({ page }) => {
    await openSettings(page);
    await tid(page, "field-holding").fill("26"); // so Save is enabled
    await page.locator("body").click({ position: { x: 1, y: 1 } });
    await page.keyboard.press("Control+Home");
    for (const id of ["field-ack", "field-holding", "field-sla", "field-role", "open-mon", "quiet-on", "save"]) {
      await tabTo(page, id);
      // Buttons fade their outline colour in (a 150 ms transition), so wait for it to settle instead of reading it at once.
      await expect
        .poll(
          () =>
            page.evaluate(() => {
              const s = getComputedStyle(document.activeElement!);
              return { style: s.outlineStyle, width: s.outlineWidth, color: s.outlineColor };
            }),
          { message: `the focus ring on ${id}` },
        )
        .toEqual({ style: "solid", width: "3px", color: "rgb(47, 107, 16)" });
    }
  });

  test("the leave dialog works from the keyboard and gives focus back to the link", async ({ page }) => {
    await openSettings(page);
    await tid(page, "field-sla").fill("48");
    const link = page.getByRole("link", { name: /All clinic products/ });
    await link.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog", { name: "Leave without saving?" });
    await expect(dialog).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(link).toBeFocused();
    await expect(tid(page, "field-sla")).toHaveValue("48");
  });

  test("the error summary can be used from the keyboard", async ({ page }) => {
    await openSettings(page);
    await tid(page, "field-holding").fill("3");
    await tid(page, "save").focus();
    await page.keyboard.press("Enter");
    const summary = tid(page, "error-summary");
    await expect(summary).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(summary.getByRole("link", { name: "Holding message" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(tid(page, "field-holding")).toBeFocused();
  });
});
