import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import { resolve, dirname } from "node:path";
import { test, expect, type Page } from "@playwright/test";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../../../..");
const script = "packages/features/reactivation/scripts/browser_seed.py";

// The helper only ever uses the disposable TEST_* databases and refuses anything else.
function helper(command: string, name: string, extra: string[] = []) {
  execFileSync("uv", ["run", "python", script, command, "--tenant-name", name, ...extra], {
    cwd: repoRoot,
    env: process.env,
    encoding: "utf8",
  });
}

async function signIn(page: Page, workspace: string) {
  await page.goto("/login");
  await page.getByRole("link", { name: "Continue with Google" }).click();
  await expect(page).toHaveURL(/\/onboarding$/);
  await page.getByLabel("Workspace name").fill(workspace);
  await page.getByRole("button", { name: "Create workspace", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
}

let workspace: string;
test.beforeEach(async ({ page }) => {
  workspace = `ShellMode ${randomUUID().slice(0, 8)}`;
  await signIn(page, workspace);
});
test.afterEach(() => {
  helper("cleanup", workspace);
});

const badge = (page: Page) => page.getByTestId("mode-badge");
const card = (page: Page) => page.getByTestId("status-card");
const footer = (page: Page) => page.getByTestId("shell-footer");
const main = (page: Page) => page.getByRole("main");

const SAVED_TEXT = "These figures come from your clinic's last saved analysis.";
const FILE_TEXT = "Analysed from your file in this browser. Not saved. Refreshing the page clears them.";
const NONE_TEXT = "Nothing has been analysed yet. Run an analysis or import a CSV file to see your dormant patients.";

const day = (daysAgo: number) => new Date(Date.now() - daysAgo * 86_400_000).toISOString().slice(0, 10);
function csvFile(patients: number) {
  const lines = ["patient_id,patient_name,email,phone,sms_consent,visit_date,line_kind,service_name,service_category,amount"];
  for (let i = 0; i < patients; i++) {
    const last = 200 + ((i * 17) % 500);
    for (let k = 0; k < 3; k++)
      lines.push(
        [`P${i}`, `Person ${i}`, `p${i}@example.test`, `555010${String(i).padStart(4, "0")}`, "yes", day(last + 60 * k), "service", i % 2 ? "Botox" : "Facial", i % 2 ? "Injectables" : "Facials", `${150 + i * 7}.00`].join(","),
      );
  }
  return { name: "march-export.csv", mimeType: "text/csv", buffer: Buffer.from(lines.join("\n") + "\n") };
}

test("with a saved analysis, the badge, the card and the footer say so", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.goto("/reactivation");
  await expect(badge(page)).toHaveText("Saved data");
  await expect(card(page)).toContainText("Saved analysis");
  await expect(card(page)).toContainText(SAVED_TEXT);
  await expect(footer(page)).toHaveText("Avishkar Dormant patients · Showing your last saved analysis");
  await page.getByRole("navigation", { name: "Dormant patients sections" }).getByRole("link", { name: "Runs" }).click();
  await expect(badge(page)).toHaveText("Saved data");
});

test("with no analysis and no file, the frame does not claim a saved analysis", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "empty"]);
  await page.goto("/reactivation");
  await expect(badge(page)).toHaveText("No saved data");
  await expect(card(page)).toContainText("No analysis yet");
  await expect(card(page)).toContainText(NONE_TEXT);
  await expect(card(page)).not.toContainText(/last saved analysis/i);
  await expect(card(page)).not.toContainText("Saved analysis");
  await expect(footer(page)).toHaveText("Avishkar Dormant patients · No analysis yet");
  await expect(footer(page)).not.toContainText(/saved analysis/i);
});

test("with file results open, the badge and the card say they are from a file and not saved", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.goto("/reactivation/import");
  await expect(page.getByTestId("csv-choose")).toBeFocused(); // hydrated
  await page.getByTestId("csv-file-input").setInputFiles(csvFile(25));
  await expect(main(page).getByTestId("csv-banner")).toContainText("march-export.csv", { timeout: 60_000 });

  await expect(badge(page)).toHaveText("From file"); // words, not only blue
  await expect(card(page)).toHaveAttribute("data-mode", "file");
  await expect(card(page)).toContainText("File results");
  await expect(card(page)).toContainText(FILE_TEXT);
  await expect(footer(page)).toHaveText("Avishkar Dormant patients · Showing results from a file, not saved");

  // the file pages are about the file; Runs is about saved data, so the frame goes back to saying so
  await page.getByRole("navigation", { name: "Dormant patients data" }).getByRole("link", { name: "Imported file" }).click();
  await expect(badge(page)).toHaveText("From file");
  await page.getByRole("navigation", { name: "Dormant patients sections" }).getByRole("link", { name: "Runs" }).click();
  await expect(badge(page)).toHaveText("Saved data");
  await expect(card(page)).toContainText(SAVED_TEXT);

  await page.getByRole("navigation", { name: "Dormant patients sections" }).getByRole("link", { name: "Overview" }).click();
  await expect(badge(page)).toHaveText("From file");
  await main(page).getByTestId("csv-back").click(); // back to saved data
  await expect(badge(page)).toHaveText("Saved data");

  await page.setViewportSize({ width: 768, height: 1000 });
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(over, "the page should not scroll sideways").toBeLessThanOrEqual(1);
});

test("the profile block shows the person and their role, and falls back plainly when a field is missing", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.goto("/reactivation");
  await expect(page.getByTestId("profile-name")).toHaveText("Browser Owner");
  await expect(page.getByTestId("profile-role")).toHaveText("owner");
  await expect(page.getByTestId("profile").locator(".dp-avatar")).toHaveText("BO");
  await expect(page.getByTestId("clinic-name")).toHaveText(workspace);

  // no name: the email; no email either: "Signed in"
  let user: { display_name: string; email: string } | null = null;
  await page.route("**/api/v1/auth/me", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    if (user) body.user = { ...body.user, ...user };
    await route.fulfill({ response, json: body });
  });
  user = { display_name: "", email: "maya@example.test" };
  await page.goto("/reactivation");
  await expect(page.getByTestId("profile-name")).toHaveText("maya@example.test");
  await expect(page.getByTestId("profile").locator(".dp-avatar")).toHaveText("M");
  user = { display_name: "", email: "" };
  await page.goto("/reactivation");
  await expect(page.getByTestId("profile-name")).toHaveText("Signed in");
});

test("Sign out ends the session and goes to the login page", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.goto("/reactivation");
  await page.getByRole("complementary").getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/reactivation");
  await expect(page).toHaveURL(/\/login/); // the session is gone
});
