import { execFile, execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import { resolve, dirname } from "node:path";
import { test, expect, type Page } from "@playwright/test";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../../../..");
const script = "packages/features/reactivation/scripts/browser_seed.py";
const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});
const dollars = (cents: number) => money.format(cents / 100);

type Facts = {
  dormant: number;
  total: number;
  low: number;
  high: number;
  newly: number;
  returned: number;
  unclassified: number;
};

// The helper only ever uses the disposable TEST_* databases and refuses anything else.
function helper(command: string, name: string, extra: string[] = []) {
  const out = execFileSync(
    "uv",
    ["run", "python", script, command, "--tenant-name", name, ...extra],
    { cwd: repoRoot, env: process.env, encoding: "utf8" },
  );
  return JSON.parse(out.trim().split("\n").pop()!) as Facts;
}

async function signIn(page: Page, workspace: string) {
  await page.goto("/login");
  await page.getByRole("link", { name: "Continue with Google" }).click();
  await expect(page).toHaveURL(/\/onboarding$/);
  await page.getByLabel("Workspace name").fill(workspace);
  await page
    .getByRole("button", { name: "Create workspace", exact: true })
    .click();
  await expect(page).toHaveURL(/\/$/);
}

let workspace: string;
test.beforeEach(async ({ page }) => {
  workspace = `Dormant ${randomUUID().slice(0, 8)}`;
  await signIn(page, workspace);
});
test.afterEach(() => {
  helper("cleanup", workspace);
});

// Next streams a hidden copy of the page while it loads, so look inside <main> only.
const tid = (page: Page, id: string) => page.getByRole("main").getByTestId(id);

async function noHorizontalScroll(page: Page) {
  const problems = await page.evaluate(() => {
    const over = document.documentElement.scrollWidth - window.innerWidth;
    if (over <= 1) return [];
    const name = (e: Element) => e.tagName + "." + e.className;
    const clipped = (e: Element) => {
      for (let n = e.parentElement; n; n = n.parentElement)
        if (getComputedStyle(n).overflowX !== "visible") return true;
      return false;
    };
    const spilling = [...document.querySelectorAll("*")]
      .filter((e) => e.getBoundingClientRect().right > window.innerWidth + 1 && !clipped(e))
      .slice(0, 6)
      .map((e) => `${name(e)} ends at ${Math.round(e.getBoundingClientRect().right)}px`);
    return [`page is ${over}px too wide (inner ${window.innerWidth}, doc ${document.documentElement.scrollWidth}, body ${document.body.scrollWidth}, client ${document.documentElement.clientWidth})`, ...spilling];
  });
  expect(problems, "the page should not scroll sideways").toEqual([]);
}

test("the overview shows tiles, the types table and the unavailable state", async ({
  page,
}, info) => {
  const f = helper("seed", workspace, ["--scenario", "full"]);
  await page.goto("/reactivation");

  // Navigation: the section, its tabs and the platform sidebar entry.
  await expect(page.getByRole("link", { name: "Dormant patients" })).toBeVisible();
  const tabs = page.getByRole("navigation", { name: "Dormant patients sections" });
  await expect(tabs.getByRole("link")).toHaveText(["Overview", "Runs", "Settings"]);
  await expect(tabs.getByRole("link", { name: "Overview" })).toHaveAttribute(
    "aria-current",
    "page",
  );

  await expect(tid(page, "last-analysed")).toContainText(
    "Last analysed 3 hours ago",
  );
  await expect(tid(page, "run-now")).toBeEnabled();

  // Tiles come straight from the stored summary.
  const dormant = tid(page, "tile-dormant");
  await expect(dormant).toContainText(String(f.dormant));
  await expect(dormant).toContainText(`of ${f.total} patients`);
  await expect(tid(page, "tile-revenue")).toContainText(
    `${dollars(f.low)} to ${dollars(f.high)}`,
  );
  const change = tid(page, "tile-change");
  await expect(change).toContainText(`${f.newly} newly dormant`);
  await expect(change).toContainText(`${f.returned} came back`);

  // One row per enabled type, unclassified last.
  const rows = page.locator("[data-testid^='type-row-']");
  await expect(rows).toHaveCount(8); // seven types plus unclassified
  await expect(rows.last()).toHaveAttribute("data-testid", "type-row-unclassified");
  await expect(rows.last()).toContainText(String(f.unclassified));
  await expect(rows.last()).toContainText("Not estimated");

  const overdue = tid(page, "type-row-overdue_maintenance");
  await expect(overdue).toContainText("Overdue maintenance");
  await expect(overdue).toContainText("Neurotoxin");
  await expect(overdue).toContainText("At an assumed return rate");
  await expect(overdue).toContainText(/\$\d[\d,]* to \$\d[\d,]*/);

  // Retention is shown as money already paid, not as a range.
  const balance = tid(page, "type-row-unused_balance");
  await expect(balance).toContainText("$6,400");
  await expect(balance).toContainText("already paid, locked in");

  // Missing source data is "Not available", never zero.
  const churned = tid(page, "type-row-churned_member");
  await expect(churned).toContainText("Not available for this clinic");
  await expect(churned).toContainText("No membership records have been imported.");
  await expect(churned.locator("td").nth(1)).toHaveText("Not available");
  await expect(churned).not.toContainText("$0");

  // The data notes are collapsed until opened.
  const about = tid(page, "about-data");
  await expect(about).not.toHaveAttribute("open", "");
  await about.getByText(/About this data/).click();
  await expect(about).toContainText("Staff records haven't been imported");
  await expect(about).toContainText("can't be imported yet");
  await expect(about).toContainText("3 patients under 18 were left out.");
  for (const raw of ["cohort_too_small_for_percentile", "excluded_minor"])
    await expect(page.locator("body")).not.toContainText(raw);

  // Keyboard: the type name is a real link.
  await overdue.getByRole("link", { name: "Overdue maintenance" }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/reactivation\/types\/overdue_maintenance$/);
  await page.goBack();

  // Clicking anywhere on a row goes to the type page.
  await tid(page, "type-row-one_and_done").locator("td").nth(3).click();
  await expect(page).toHaveURL(/\/reactivation\/types\/one_and_done$/);
  await page.goBack();

  for (const width of [1440, 768]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/reactivation");
    await expect(tid(page, "tile-dormant")).toBeVisible();
    await noHorizontalScroll(page);
    await page.screenshot({
      path: info.outputPath(`overview-${width}.png`),
      fullPage: true,
    });
  }
});

test("a first analysis says so, and the placeholder routes exist", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "first"]);
  await page.goto("/reactivation");
  await expect(tid(page, "tile-change")).toContainText("First analysis");
  await expect(tid(page, "tile-change")).not.toContainText("newly dormant");
  for (const [path, heading] of [
    ["/reactivation/runs", "Runs"],
    ["/reactivation/settings", "Settings"],
    ["/reactivation/types/one_and_done", "Patients of this type"],
  ]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
  }
});

test("a failed run shows a plain message and keeps the previous results", async ({
  page,
}) => {
  const f = helper("seed", workspace, ["--scenario", "failed"]);
  await page.goto("/reactivation");
  const alert = page.getByRole("main").getByRole("alert");
  await expect(alert).toContainText("The last analysis didn't finish.");
  await expect(alert).toContainText("took too long");
  await expect(alert).not.toContainText("timed_out");
  await expect(tid(page, "tile-dormant")).toContainText(String(f.dormant));
});

test("with no analysis yet, Run now starts one, shows progress and refreshes when it completes", async ({
  page,
}, info) => {
  helper("seed", workspace, ["--scenario", "none"]);
  await page.goto("/reactivation");
  await expect(
    page.getByRole("heading", { name: "Find the patients who've gone quiet" }),
  ).toBeVisible();
  await expect(tid(page, "last-analysed")).toHaveText("Not analysed yet");
  await page.screenshot({ path: info.outputPath("first-run-1440.png"), fullPage: true });

  const start = tid(page, "run-now");
  await start.click();
  await expect(start).toBeDisabled();
  await expect(tid(page, "progress-card")).toBeVisible();
  await expect(tid(page, "progress-stage")).toContainText("Waiting to start");

  // Stand in for the worker, which the browser test server does not run.
  const worker = new Promise<void>((done, fail) =>
    execFile(
      "uv",
      ["run", "python", script, "work", "--tenant-name", workspace, "--delay", "2"],
      { cwd: repoRoot, env: process.env },
      (error) => (error ? fail(error) : done()),
    ),
  );
  await expect(tid(page, "tile-dormant")).toBeVisible({ timeout: 45_000 });
  await worker;
  await expect(tid(page, "progress-card")).toHaveCount(0);
  await expect(tid(page, "last-analysed")).toContainText("Last analysed just now");
  await expect(tid(page, "run-now")).toBeEnabled();
  // An empty clinic is explained rather than shown as a bare zero.
  await tid(page, "about-data").getByText(/About this data/).click();
  await expect(tid(page, "about-data")).toContainText("No patients were found");
});

test("roles that cannot start runs do not see Run now", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.route("**/api/v1/auth/me", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    for (const m of body.memberships) m.role = "front_desk";
    await route.fulfill({ response, json: body });
  });
  await page.goto("/reactivation");
  await expect(tid(page, "tile-dormant")).toBeVisible();
  await expect(tid(page, "run-now")).toHaveCount(0);
});
