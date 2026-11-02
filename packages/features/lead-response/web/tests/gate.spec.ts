import { test, expect } from "@playwright/test";
import { tid, useWorkspace } from "./helpers";

test.describe("a clinic that does not have the feature", () => {
  useWorkspace({ scenario: null }); // signed in, owner, feature NOT switched on

  test("the page is a 404, not an error and not the form", async ({ page }) => {
    const response = await page.goto("/lead-response/settings");
    await expect(page.getByText("This page could not be found.")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("main").getByTestId("settings-form")).toHaveCount(0);
    await expect(page.getByTestId("settings-error")).toHaveCount(0);
    await expect(page.getByTestId("settings-forbidden")).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Settings", exact: true })).toHaveCount(0); // none of the feature's own frame
    // Recorded rather than assumed: the not-found answer is decided after the page has begun to stream.
    test.info().annotations.push({ type: "http status of the first response", description: String(response?.status()) });
  });

  test("the product home address is a 404 as well, and the API's own answer is the exact text the page matches", async ({ page }) => {
    await page.goto("/lead-response");
    await expect(page.getByText("This page could not be found.")).toBeVisible({ timeout: 30_000 });
    const read = await page.request.get("/api/platform/features/lead_response/settings");
    expect(read.status()).toBe(403);
    expect(await read.json()).toEqual({ detail: "Feature 'lead_response' is not enabled" });
    await expect(tid(page, "settings-form")).toHaveCount(0);
  });
});
