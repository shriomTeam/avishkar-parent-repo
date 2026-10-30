import { test, expect } from "@playwright/test";
import { API_SETTINGS, openSettings, shot, tid, useWorkspace } from "./helpers";

test.describe("checking values before they are sent", () => {
  useWorkspace({ scenario: "standard" });

  test("a number outside its range is explained in the box's own words, and the error goes when it is fixed", async ({ page }) => {
    await openSettings(page);
    const holding = tid(page, "field-holding");
    await holding.fill("4");
    await holding.press("Tab");
    await expect(tid(page, "field-holding-error")).toHaveText("Enter a number from 5 to 60.");
    await expect(holding).toHaveAttribute("aria-invalid", "true");
    await expect(holding).toHaveAttribute("aria-describedby", /field-holding-error/);
    await expect(tid(page, "field-holding-error").locator("svg")).toHaveCount(1); // an icon, so colour is not the only signal
    await holding.fill("5");
    await expect(tid(page, "field-holding-error")).toHaveCount(0);
    await expect(holding).not.toHaveAttribute("aria-invalid", "true");
    for (const [raw, message] of [
      ["", "Enter a number."],
      ["ten", "Use a whole number, with no letters or decimals."],
      ["7.5", "Use a whole number, with no letters or decimals."],
      ["61", "Enter a number from 5 to 60."],
    ] as const) {
      await holding.fill(raw);
      await expect(tid(page, "field-holding-error")).toHaveText(message);
    }
  });

  test("the staff target must be longer than the holding time", async ({ page }) => {
    await openSettings(page);
    await tid(page, "field-holding").fill("40");
    await tid(page, "field-sla").fill("40");
    await tid(page, "field-sla").press("Tab");
    await expect(tid(page, "field-sla-error")).toHaveText("The staff response target must be longer than the holding message time (40 minutes).");
    await tid(page, "field-sla").fill("41");
    await expect(tid(page, "field-sla-error")).toHaveCount(0);
    await tid(page, "field-sla").fill("9");
    await expect(tid(page, "field-sla-error")).toHaveText("Enter a number from 10 to 240.");
  });

  test("the instant reply: empty, too long, brackets and hidden characters each get their own sentence, with a live count", async ({ page }) => {
    await openSettings(page);
    const ack = tid(page, "field-ack");
    await ack.fill("");
    await ack.press("Tab");
    await expect(tid(page, "field-ack-error")).toHaveText("Write the message a new lead receives.");
    await expect(tid(page, "field-ack-count")).toHaveText("0 of 320 characters");
    await ack.fill("a".repeat(321));
    await expect(tid(page, "field-ack-error")).toHaveText("Shorten this to 320 characters or fewer. It is 321.");
    await expect(tid(page, "field-ack-count")).toHaveText("321 of 320 characters");
    await ack.fill("Hi {name}");
    await expect(tid(page, "field-ack-error")).toContainText("Remove the curly brackets");
    await ack.fill("Hi​there");
    await expect(tid(page, "field-ack-error")).toHaveText("Use plain text only. Remove special or hidden characters.");
    await ack.fill("a".repeat(320));
    await expect(tid(page, "field-ack-error")).toHaveCount(0);
    await expect(tid(page, "field-ack-count")).toHaveText("320 of 320 characters");
  });

  test("hours that overlap, run backwards or are unfinished are refused for that day only", async ({ page }) => {
    await openSettings(page);
    await tid(page, "open-mon").check();
    await tid(page, "start-mon-0").fill("09:00");
    await tid(page, "end-mon-0").fill("12:00");
    await tid(page, "add-mon").click();
    await tid(page, "start-mon-1").fill("11:00");
    await tid(page, "end-mon-1").fill("14:00");
    await tid(page, "end-mon-1").press("Tab");
    await expect(tid(page, "field-hours-mon-error")).toHaveText("These time ranges overlap. Change one so they don't.");
    await expect(tid(page, "field-hours-tue-error")).toHaveCount(0);
    await tid(page, "start-mon-1").fill("12:00");
    await expect(tid(page, "field-hours-mon-error")).toHaveCount(0);
    await tid(page, "end-mon-0").fill("08:00");
    await expect(tid(page, "field-hours-mon-error")).toHaveText("Each range must end after it starts.");
    await tid(page, "end-mon-0").fill("");
    await expect(tid(page, "field-hours-mon-error")).toHaveText("Set a start and an end time for each range.");
  });

  test("quiet hours need two different times", async ({ page }) => {
    await openSettings(page);
    await tid(page, "quiet-on").check();
    await tid(page, "quiet-start").fill("20:00");
    await tid(page, "quiet-end").fill("20:00");
    await tid(page, "quiet-end").press("Tab");
    await expect(tid(page, "field-quiet-error")).toHaveText("The start and end times must be different.");
    await tid(page, "quiet-end").fill("06:00");
    await expect(tid(page, "field-quiet-error")).toHaveCount(0);
  });

  test("pressing Save with problems sends nothing, lists them, moves focus to the list, and its links go to the boxes", async ({ page }) => {
    await openSettings(page);
    const sent: string[] = [];
    page.on("request", (r) => {
      if (r.method() === "PUT" && r.url().includes("lead_response")) sent.push(r.url());
    });
    await tid(page, "field-ack").fill("");
    await tid(page, "field-holding").fill("4");
    await tid(page, "field-sla").fill("1");
    await tid(page, "save").click();
    const summary = tid(page, "error-summary");
    await expect(summary).toBeFocused();
    await expect(summary).toContainText("There are 3 things to fix before you can save");
    await expect(summary.getByRole("listitem")).toHaveCount(3);
    await expect(tid(page, "save-status")).toHaveText("Fix 3 things before saving.");
    await expect(tid(page, "field-ack-error")).toBeVisible();
    await shot(page, "validation-summary-" + page.viewportSize()!.width);
    await summary.getByRole("link", { name: "Holding message" }).click();
    await expect(tid(page, "field-holding")).toBeFocused();
    await tid(page, "field-ack").fill("Thanks!");
    await tid(page, "field-holding").fill("15");
    await tid(page, "field-sla").fill("30");
    await expect(summary).toHaveCount(0);
    expect(sent).toEqual([]);
  });

  test("a value the server refuses anyway is a plain message for the whole form, not a field error", async ({ page }) => {
    await openSettings(page);
    await page.route(API_SETTINGS, (route) =>
      route.request().method() === "PUT"
        ? route.fulfill({ status: 422, contentType: "application/json", body: '{"detail":"invalid_request"}' })
        : route.continue(),
    );
    await tid(page, "field-holding").fill("20");
    await tid(page, "save").click();
    const problem = tid(page, "save-problem");
    await expect(problem).toHaveAttribute("data-problem", "invalid");
    await expect(problem).toContainText("We couldn't accept these settings.");
    await expect(problem).not.toContainText("invalid_request");
    await expect(problem).toBeFocused();
    await expect(tid(page, "field-holding")).toHaveValue("20"); // what the person typed is kept
  });
});
