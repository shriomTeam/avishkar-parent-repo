import { test, expect } from "@playwright/test";
import { API_SETTINGS, openSettings, seed, tid, useWorkspace } from "./helpers";

test.describe("when a save does not go through", () => {
  const workspace = useWorkspace({ scenario: "standard" });

  test("someone saved first: the page says so, keeps your edits until you reload, and reload shows theirs", async ({ page }) => {
    await openSettings(page);
    await tid(page, "field-ack").fill("My own wording for the reply.");
    const other = seed("bump", workspace()); // another person's save, behind this page's back
    expect(other.version).toBe(1);
    await tid(page, "save").click();
    const problem = tid(page, "save-problem");
    await expect(problem).toHaveAttribute("data-problem", "stale");
    await expect(problem).toContainText("Settings changed elsewhere. Reload.");
    await expect(problem).toBeFocused();
    await expect(tid(page, "field-ack")).toHaveValue("My own wording for the reply.");
    await expect(tid(page, "settings-status")).toHaveText("Using the standard settings.");
    const asked: string[] = [];
    page.on("dialog", (dialog) => {
      asked.push(dialog.type());
      void dialog.accept();
    });
    await tid(page, "reload").click();
    await expect(tid(page, "settings-form")).toHaveAttribute("data-ready", "true");
    await expect(tid(page, "settings-status")).toContainText("Using your saved settings (version 1).");
    await expect(tid(page, "field-holding")).toHaveValue("16"); // the other person's change
    await expect(tid(page, "field-ack")).toHaveValue(/We have received it/); // my edit is gone
    await expect(tid(page, "save-problem")).toHaveCount(0);
    expect(asked, "reloading from the conflict message must not ask whether to leave").toEqual([]);
  });

  test("a server failure keeps the edits, says nothing was changed, and a second try works", async ({ page }) => {
    await openSettings(page);
    let fail = true;
    await page.route(API_SETTINGS, (route) => {
      if (route.request().method() !== "PUT") return route.continue();
      return fail ? route.fulfill({ status: 500, contentType: "application/json", body: "{}" }) : route.continue();
    });
    await tid(page, "field-holding").fill("22");
    await tid(page, "save").click();
    await expect(tid(page, "save-problem")).toHaveAttribute("data-problem", "failed");
    await expect(tid(page, "save-problem")).toContainText("Nothing was changed.");
    await expect(tid(page, "field-holding")).toHaveValue("22");
    await expect(tid(page, "save")).toBeEnabled();
    fail = false;
    await tid(page, "save").click();
    await expect(tid(page, "saved-notice")).toContainText("Saved (version 1).");
    await expect(tid(page, "save-problem")).toHaveCount(0);
  });

  test("a lost connection is the same: edits kept, retry works", async ({ page }) => {
    await openSettings(page);
    let down = true;
    await page.route(API_SETTINGS, (route) => {
      if (route.request().method() !== "PUT") return route.continue();
      return down ? route.abort("connectionfailed") : route.continue();
    });
    await tid(page, "field-sla").fill("55");
    await tid(page, "save").click();
    await expect(tid(page, "save-problem")).toHaveAttribute("data-problem", "failed");
    await expect(tid(page, "field-sla")).toHaveValue("55");
    down = false;
    await tid(page, "save").click();
    await expect(tid(page, "saved-notice")).toBeVisible();
  });

  test("the server saying AI is not available yet gets its own message", async ({ page }) => {
    await openSettings(page);
    await page.route(API_SETTINGS, (route) =>
      route.request().method() === "PUT"
        ? route.fulfill({ status: 422, contentType: "application/json", body: '{"detail":"ai_settings_not_available_yet"}' })
        : route.continue(),
    );
    await tid(page, "field-holding").fill("21");
    await tid(page, "save").click();
    await expect(tid(page, "save-problem")).toHaveAttribute("data-problem", "ai_not_available");
    await expect(tid(page, "save-problem")).toContainText("AI replies aren't available yet.");
  });
});
