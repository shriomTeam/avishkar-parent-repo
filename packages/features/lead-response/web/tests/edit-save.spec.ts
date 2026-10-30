import { test, expect } from "@playwright/test";
import { API_SETTINGS, openSettings, shot, tid, useWorkspace } from "./helpers";

const SAVED = "Saved (version 1). These settings take effect when lead response is switched on for your clinic.";

test.describe("editing and saving", () => {
  useWorkspace({ scenario: "standard" });

  test("a changed timer rewrites its example, saves, says what changed, and is still there after a reload", async ({ page }) => {
    await openSettings(page);
    await tid(page, "field-holding").fill("25");
    await expect(tid(page, "field-holding-help")).toContainText("At 10:25 am (after 25 minutes)");
    await expect(tid(page, "save-status")).toHaveText("You have unsaved changes.");
    await tid(page, "save").click();
    await expect(tid(page, "saved-notice")).toContainText(SAVED);
    await expect(tid(page, "saved-notice")).toContainText("Changed: Holding message time.");
    await expect(tid(page, "settings-status")).toContainText("Using your saved settings (version 1).");
    await expect(tid(page, "save-status")).toHaveText("No unsaved changes.");
    await expect(tid(page, "save")).toBeDisabled();
    await shot(page, "edit-saved-" + page.viewportSize()!.width);
    await page.reload();
    await expect(tid(page, "settings-form")).toHaveAttribute("data-ready", "true");
    await expect(tid(page, "field-holding")).toHaveValue("25");
  });

  test("wording, hours, who is told and quiet hours all save, and the server's order and trimming are shown back", async ({ page }) => {
    await openSettings(page);
    await tid(page, "field-ack").fill("  Hello from the clinic. We will reply soon.  ");
    await tid(page, "field-role").selectOption("owner");
    await tid(page, "open-mon").check();
    await tid(page, "start-mon-0").fill("13:00");
    await tid(page, "end-mon-0").fill("17:00");
    await tid(page, "add-mon").click();
    await tid(page, "start-mon-1").fill("08:00");
    await tid(page, "end-mon-1").fill("12:00");
    await tid(page, "quiet-on").check();
    await tid(page, "quiet-start").fill("22:00");
    await tid(page, "quiet-end").fill("07:00");
    await tid(page, "save").click();
    await expect(tid(page, "saved-notice")).toContainText("Changed: Instant reply wording, Who is told, Business hours, Quiet hours.");
    await expect(tid(page, "field-ack")).toHaveValue("Hello from the clinic. We will reply soon.");
    await expect(tid(page, "start-mon-0")).toHaveValue("08:00");
    await expect(tid(page, "start-mon-1")).toHaveValue("13:00");
    await expect(tid(page, "summary-mon")).toHaveText("8:00 am to 12:00 pm, 1:00 pm to 5:00 pm");
    await page.reload();
    await expect(tid(page, "settings-form")).toHaveAttribute("data-ready", "true");
    await expect(tid(page, "field-role")).toHaveValue("owner");
    await expect(tid(page, "quiet-start")).toHaveValue("22:00");
    await expect(tid(page, "quiet-example")).toContainText("10:00 pm to 7:00 am in your clinic's time zone");
  });

  test("discard puts back what was saved", async ({ page }) => {
    await openSettings(page);
    await tid(page, "field-sla").fill("90");
    await tid(page, "open-tue").check();
    await expect(tid(page, "save-status")).toHaveText("You have unsaved changes.");
    await tid(page, "discard").click();
    await expect(tid(page, "field-sla")).toHaveValue("30");
    await expect(tid(page, "open-tue")).not.toBeChecked();
    await expect(tid(page, "save-status")).toHaveText("No unsaved changes.");
  });

  test("a closed day can be opened and closed again, and a range can be removed", async ({ page }) => {
    await openSettings(page);
    await tid(page, "open-wed").check();
    await expect(tid(page, "summary-wed")).toHaveText("9:00 am to 5:00 pm");
    await tid(page, "add-wed").click();
    await expect(tid(page, "window-wed-1")).toBeVisible();
    await tid(page, "remove-wed-1").click();
    await expect(tid(page, "window-wed-1")).toHaveCount(0);
    await tid(page, "open-wed").uncheck();
    await expect(tid(page, "summary-wed")).toHaveText("Closed");
    await expect(tid(page, "save-status")).toHaveText("No unsaved changes.");
  });

  test("while saving, the button is busy and a second click sends nothing more", async ({ page }) => {
    await openSettings(page);
    let puts = 0;
    await page.route(API_SETTINGS, async (route) => {
      if (route.request().method() === "PUT") {
        puts++;
        await new Promise((r) => setTimeout(r, 1500));
      }
      await route.continue();
    });
    await tid(page, "field-holding").fill("30");
    await tid(page, "field-sla").fill("50");
    await tid(page, "save").click();
    await expect(tid(page, "save")).toHaveText("Saving…");
    await expect(tid(page, "save")).toBeDisabled();
    await expect(tid(page, "save")).toHaveAttribute("aria-busy", "true");
    await expect(tid(page, "save-status")).toHaveText("Saving…");
    await tid(page, "save").click({ force: true }).catch(() => {});
    await expect(tid(page, "saved-notice")).toBeVisible();
    expect(puts).toBe(1);
  });
});

test.describe("reset to standard settings", () => {
  useWorkspace({ scenario: "saved" });

  test("fills the standard values, saves nothing until Save, then saves them as a new version", async ({ page }) => {
    await openSettings(page);
    await tid(page, "reset").click();
    await expect(tid(page, "reset-notice")).toContainText("The standard settings are filled in. Nothing is saved until you press Save.");
    await expect(tid(page, "field-holding")).toHaveValue("15");
    await expect(tid(page, "field-sla")).toHaveValue("30");
    await expect(tid(page, "field-role")).toHaveValue("office_manager");
    await expect(tid(page, "quiet-on")).not.toBeChecked();
    await expect(tid(page, "summary-mon")).toHaveText("Closed");
    await expect(tid(page, "reset")).toBeDisabled();
    await expect(tid(page, "save-status")).toHaveText("You have unsaved changes.");
    await page.reload(); // nothing was saved: the saved version is still there
    await expect(tid(page, "settings-form")).toHaveAttribute("data-ready", "true");
    await expect(tid(page, "field-holding")).toHaveValue("20");
    await tid(page, "reset").click();
    await tid(page, "save").click();
    await expect(tid(page, "saved-notice")).toContainText("Saved (version 3).");
    await expect(tid(page, "saved-notice")).toContainText("Changed:");
    await page.reload();
    await expect(tid(page, "settings-form")).toHaveAttribute("data-ready", "true");
    await expect(tid(page, "field-holding")).toHaveValue("15");
    await expect(tid(page, "reset")).toBeDisabled();
  });
});
