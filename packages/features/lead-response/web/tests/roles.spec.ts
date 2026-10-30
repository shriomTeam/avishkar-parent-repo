import { test, expect } from "@playwright/test";
import { API_SETTINGS, openSettings, shot, tid, useWorkspace } from "./helpers";

test.describe("a role the platform refuses (a real front desk member)", () => {
  useWorkspace({ scenario: "standard", role: "front_desk" });

  test("sees the role view, no form, and the API itself answers 403", async ({ page }) => {
    await page.goto("/lead-response/settings");
    await expect(tid(page, "settings-forbidden")).toBeVisible({ timeout: 30_000 });
    await expect(tid(page, "settings-forbidden")).toContainText("Only the owner or office manager can change these settings");
    await expect(tid(page, "settings-form")).toHaveCount(0);
    // The profile block is in the sidebar, outside <main>; Next also streams a hidden copy of the page, so take the visible one.
    await expect(page.locator('[data-testid="profile-role"]:visible')).toHaveText("front desk");
    await shot(page, "role-view-" + page.viewportSize()!.width);
    // The enforcement is on the server: ask it directly, with the same session.
    const read = await page.request.get("/api/platform/features/lead_response/settings");
    expect(read.status()).toBe(403);
    expect(await read.json()).toEqual({ detail: "feature_access_denied" });
  });
});

test.describe("a save the server refuses for the role", () => {
  useWorkspace({ scenario: "standard" });

  // The browser can only fake the answer here (the real owner is allowed); the server's own 403 for roles is proved
  // by the front desk test above and by tests/test_settings_roles.py, which exercises every role against the API.
  test("a 403 on save says so, keeps the edits and offers no retry loop", async ({ page }) => {
    await openSettings(page);
    await page.route(API_SETTINGS, (route) =>
      route.request().method() === "PUT"
        ? route.fulfill({ status: 403, contentType: "application/json", body: '{"detail":"Not allowed for your role"}' })
        : route.continue(),
    );
    await tid(page, "field-holding").fill("19");
    await tid(page, "save").click();
    const problem = tid(page, "save-problem");
    await expect(problem).toHaveAttribute("data-problem", "forbidden");
    await expect(problem).toContainText("You can't change these settings.");
    await expect(problem).toBeFocused();
    await expect(tid(page, "field-holding")).toHaveValue("19");
    await expect(tid(page, "reload")).toHaveCount(0);
  });
});
