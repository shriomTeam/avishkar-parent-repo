import { test, expect } from "@playwright/test";
import { noHorizontalScroll, openSettings, shot, tid, useWorkspace } from "./helpers";

test.describe("standard settings (no version saved yet)", () => {
  useWorkspace({ scenario: "standard" });

  test("a clinic with nothing saved sees the standard settings", async ({ page }) => {
    await openSettings(page);
    await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
    await expect(tid(page, "settings-status")).toHaveText("Using the standard settings.");
    await expect(tid(page, "field-holding")).toHaveValue("15");
    await expect(tid(page, "field-sla")).toHaveValue("30");
    await expect(tid(page, "field-role")).toHaveValue("office_manager");
    await expect(tid(page, "field-ack")).toHaveValue(/We have received it/);
    await expect(tid(page, "open-mon")).not.toBeChecked();
    await expect(tid(page, "summary-mon")).toHaveText("Closed");
    await expect(tid(page, "quiet-on")).not.toBeChecked();
    await expect(tid(page, "quiet-example")).toHaveText("No quiet hours are set.");
    await expect(tid(page, "save")).toBeDisabled();
    await expect(tid(page, "save-status")).toHaveText("No unsaved changes.");
    await expect(tid(page, "reset")).toBeDisabled();
    await noHorizontalScroll(page);
    await shot(page, "load-standard-" + page.viewportSize()!.width);
  });

  test("the sections come in the order of the flow and the time zone cannot be edited", async ({ page }) => {
    await openSettings(page);
    const titles = await page.getByRole("main").getByRole("heading", { level: 2 }).allTextContents();
    expect(titles).toEqual(["When a lead texts you", "If nobody has replied", "Hours", "AI replies"]);
    await expect(tid(page, "timezone")).toHaveText(/.+\/.+|UTC/);
    await expect(page.getByRole("main").getByLabel(/time zone/i)).toHaveCount(0);
    await expect(tid(page, "field-holding-help")).toContainText("At 10:15 am (after 15 minutes) they get a short holding message.");
    await expect(tid(page, "field-sla-help")).toContainText("by 10:30 am, the office manager is told.");
  });

  test("the AI settings are plain rows with a tag, not controls", async ({ page }) => {
    await openSettings(page);
    const ai = tid(page, "ai-section");
    await expect(ai.getByTestId("ai-row")).toHaveCount(7);
    for (const row of await ai.getByTestId("ai-row").all()) await expect(row).toContainText("Coming later");
    await expect(ai.locator("input, select, textarea, button, [role=switch], [role=checkbox]")).toHaveCount(0);
    await expect(ai).toContainText("Nothing here is switched on");
  });

  test("the product home address leads to the settings and the menu marks where you are", async ({ page }) => {
    await page.goto("/lead-response");
    await expect(page).toHaveURL(/\/lead-response\/settings$/);
    await expect(tid(page, "settings-form")).toHaveAttribute("data-ready", "true", { timeout: 30_000 });
    await expect(page.getByRole("link", { name: "Settings", exact: true })).toHaveAttribute("aria-current", "page");
    // Next also streams a hidden copy of the page, so take the visible one.
    await expect(page.locator('[data-testid="clinic-name"]:visible')).not.toBeEmpty();
  });
});

test.describe("saved settings", () => {
  useWorkspace({ scenario: "saved" });

  test("what was saved is what is shown, and the status line names the version", async ({ page }) => {
    await openSettings(page);
    await expect(tid(page, "settings-status")).toContainText("Using your saved settings (version 2). Last saved ");
    await expect(tid(page, "field-ack")).toHaveValue("Thanks for texting Glow. We have your message and will reply shortly.");
    await expect(tid(page, "field-holding")).toHaveValue("20");
    await expect(tid(page, "field-sla")).toHaveValue("60");
    await expect(tid(page, "field-role")).toHaveValue("owner");
    await expect(tid(page, "summary-mon")).toHaveText("9:00 am to 5:00 pm");
    await expect(tid(page, "summary-fri")).toHaveText("8:00 am to 12:00 pm, 1:00 pm to 4:00 pm");
    await expect(tid(page, "summary-sat")).toHaveText("Closed");
    await expect(tid(page, "quiet-on")).toBeChecked();
    await expect(tid(page, "quiet-start")).toHaveValue("21:00");
    await expect(tid(page, "quiet-end")).toHaveValue("08:00");
    await expect(tid(page, "reset")).toBeEnabled();
    await shot(page, "load-saved-" + page.viewportSize()!.width);
  });
});
