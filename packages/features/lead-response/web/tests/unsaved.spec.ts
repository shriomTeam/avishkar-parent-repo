import { test, expect } from "@playwright/test";
import { openSettings, tid, useWorkspace } from "./helpers";

const allProducts = (page: import("@playwright/test").Page) => page.getByRole("link", { name: /All clinic products/ });

test.describe("leaving with unsaved changes", () => {
  useWorkspace({ scenario: "standard" });

  test("the browser asks before the tab is closed, and does not once everything is saved", async ({ page }) => {
    await openSettings(page);
    // Chrome asks only after genuine user activation, which fill() does not give: click the box and type on the keyboard.
    await tid(page, "field-holding").click();
    await page.keyboard.press("Control+A");
    await page.keyboard.type("20");
    await expect(tid(page, "save-status")).toHaveText("You have unsaved changes.");
    // close() with runBeforeUnload returns at once, so wait for the browser's own prompt to arrive.
    const prompt = page.waitForEvent("dialog", { timeout: 10_000 });
    await page.close({ runBeforeUnload: true });
    const dialog = await prompt;
    expect(dialog.type()).toBe("beforeunload");
    await dialog.dismiss(); // stay on the page
    expect(page.isClosed()).toBe(false);
    await tid(page, "save").click();
    await expect(tid(page, "saved-notice")).toBeVisible();
    // Everything is saved: closing now must not ask, and the page must close.
    const dialogs: string[] = [];
    page.on("dialog", (d) => dialogs.push(d.type()));
    const closed = page.waitForEvent("close", { timeout: 10_000 });
    await page.close({ runBeforeUnload: true });
    await closed;
    expect(dialogs).toEqual([]);
  });

  test("a link inside the app asks in a dialog; Stay keeps everything, Leave goes", async ({ page }) => {
    await openSettings(page);
    await tid(page, "field-holding").fill("20");
    await allProducts(page).click();
    const dialog = page.getByRole("dialog", { name: "Leave without saving?" });
    await expect(dialog).toBeVisible();
    await expect(page).toHaveURL(/\/lead-response\/settings$/);
    await dialog.getByTestId("stay").click();
    await expect(dialog).toHaveCount(0);
    await expect(tid(page, "field-holding")).toHaveValue("20");
    await allProducts(page).click();
    await page.getByTestId("leave").click();
    await expect(page).toHaveURL(/\/$/);
  });

  test("with nothing to lose a link just goes, and Escape on the dialog means Stay", async ({ page }) => {
    await openSettings(page);
    await allProducts(page).click();
    await expect(page).toHaveURL(/\/$/);
    await page.goBack();
    await expect(tid(page, "settings-form")).toHaveAttribute("data-ready", "true");
    await tid(page, "field-sla").fill("44");
    await allProducts(page).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page).toHaveURL(/\/lead-response\/settings$/);
    await expect(tid(page, "field-sla")).toHaveValue("44");
  });
});
