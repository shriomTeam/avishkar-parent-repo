import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import { resolve, dirname } from "node:path";
import { test, expect, type Page } from "@playwright/test";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../../../..");
const script = "packages/features/reactivation/scripts/browser_seed.py";

// The helper only ever uses the disposable TEST_* databases and refuses anything else.
function helper(command: string, name: string, extra: string[] = []) {
  const out = execFileSync(
    "uv",
    ["run", "python", script, command, "--tenant-name", name, ...extra],
    { cwd: repoRoot, env: process.env, encoding: "utf8" },
  );
  return JSON.parse(out.trim().split("\n").pop()!) as Record<string, number | string>;
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
  workspace = `Types ${randomUUID().slice(0, 8)}`;
  await signIn(page, workspace);
});
test.afterEach(() => {
  helper("cleanup", workspace);
});

const tid = (page: Page, id: string) => page.getByRole("main").getByTestId(id);
const rowsOf = (page: Page) => tid(page, "patients-table").getByTestId("patient-row");

async function noHorizontalScroll(page: Page) {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(over, "the page should not scroll sideways").toBeLessThanOrEqual(1);
}

/** The first dollar figure in a cell, e.g. "About $1,234 to $2,345" -> 1234. */
const firstDollars = async (cell: ReturnType<typeof tid>) =>
  Number(((await cell.innerText()).match(/\$([\d,]+)/) ?? [])[1]?.replace(/,/g, ""));

const day = (daysAgo: number) =>
  new Date(Date.now() - daysAgo * 86_400_000).toISOString().slice(0, 10);

function csvFile(patients: number) {
  const lines = ["patient_id,patient_name,email,phone,sms_consent,visit_date,line_kind,service_name,service_category,amount"];
  for (let i = 0; i < patients; i++) {
    const last = 200 + ((i * 17) % 500);
    for (let k = 0; k < 3; k++)
      lines.push(
        [
          `P${i}`, `Person ${String(i).padStart(2, "0")}`, `p${i}@example.test`, `555010${String(i).padStart(4, "0")}`,
          i % 2 ? "yes" : "no", day(last + 60 * k), "service", i % 2 ? "Botox" : "Facial",
          i % 2 ? "Injectables" : "Facials", `${150 + i * 7}.00`,
        ].join(","),
      );
  }
  return { name: "export.csv", mimeType: "text/csv", buffer: Buffer.from(lines.join("\n") + "\n") };
}

test("saved mode: open a type, see its summary, then page, sort, search, filter and expand a row", async ({ page }, info) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.goto("/reactivation");
  await tid(page, "type-row-overdue_maintenance").getByRole("link", { name: "Overdue maintenance" }).click();
  await expect(page).toHaveURL(/\/reactivation\/types\/overdue_maintenance$/);

  // Header and summary row.
  await expect(tid(page, "type-title")).toHaveText("Overdue maintenance");
  await expect(page.getByRole("main")).toContainText("Repeat patients who are overdue for their usual service.");
  await expect(tid(page, "summary-patients")).toContainText("58");
  await expect(tid(page, "summary-worth")).toContainText(/\$\d[\d,]* to \$\d[\d,]*/);
  await expect(tid(page, "summary-worth")).toContainText("At an assumed return rate of 8% to 15%");
  await expect(tid(page, "summary-top-service")).toContainText("Top service");
  await expect(tid(page, "summary-top-service")).toContainText("Neurotoxin");
  await expect(page.getByRole("main")).not.toContainText("Most common service");

  // The first page: 25 rows, the best-scoring patient first, with a band instead of a raw score.
  await expect(rowsOf(page)).toHaveCount(25);
  await expect(tid(page, "result-count")).toHaveText("58 patients");
  await expect(tid(page, "page-range")).toHaveText("Showing 1 to 25 of 58");
  await expect(rowsOf(page).first()).toContainText("High");
  await expect(page.locator("body")).not.toContainText("overdue_maintenance");
  await expect(tid(page, "sort-likelihood").locator("..")).toHaveAttribute("aria-sort", "descending");

  // The likelihood number is available on keyboard focus.
  await rowsOf(page).first().locator(".dp-hint-trigger").first().focus();
  await expect(rowsOf(page).first().getByRole("tooltip")).toContainText("88 out of 100");

  // Paging goes in the URL and survives a reload.
  await tid(page, "page-next").click();
  await expect(page).toHaveURL(/\?page=2$/);
  await expect(tid(page, "page-range")).toHaveText("Showing 26 to 50 of 58");
  await page.reload();
  await expect(tid(page, "page-number")).toHaveText("Page 2 of 3");
  await expect(rowsOf(page)).toHaveCount(25);
  await tid(page, "page-next").click();
  await expect(rowsOf(page)).toHaveCount(8);
  await expect(tid(page, "page-next")).toBeDisabled();

  // Sorting by value: header toggles direction, aria-sort and the URL follow, the order really changes.
  await tid(page, "sort-value").click();
  await expect(page).toHaveURL(/sort=value/);
  await expect(page).not.toHaveURL(/page=/); // a new sort starts at page 1
  await expect(tid(page, "sort-value").locator("..")).toHaveAttribute("aria-sort", "descending");
  const high = await firstDollars(rowsOf(page).first().getByRole("cell").nth(5));
  await tid(page, "sort-value").click();
  await expect(page).toHaveURL(/dir=asc/);
  await expect(tid(page, "sort-value").locator("..")).toHaveAttribute("aria-sort", "ascending");
  await expect(async () => {
    expect(await firstDollars(rowsOf(page).first().getByRole("cell").nth(5))).toBeLessThan(high);
  }).toPass();
  await tid(page, "sort-direction").click();
  await expect(tid(page, "sort-direction")).toHaveText("Highest first");
  await page.getByTestId("sort-select").selectOption("overdue");
  await expect(page).toHaveURL(/sort=overdue/);
  await expect(tid(page, "sort-overdue").locator("..")).toHaveAttribute("aria-sort", "descending");

  // Search: by name, announced, and the text never reaches the address bar.
  await page.getByTestId("patient-search").fill("zelda");
  await expect(tid(page, "result-count")).toHaveText("1 patient match");
  await expect(rowsOf(page)).toHaveCount(1);
  await expect(rowsOf(page).first()).toContainText("Zelda Quillfeather");
  expect(page.url()).not.toContain("zelda");

  // Expand: the reasons and what we know, in plain words.
  const toggle = rowsOf(page).first().getByTestId("expand-row");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  const why = tid(page, "why-row").first();
  await expect(why).toContainText("Why they match");
  await expect(why).toContainText("Last visit");
  await expect(why).toContainText("Suggested service");
  await expect(why).toContainText("Neurotoxin, their usual service");
  await expect(why).toContainText("They usually book on");
  await expect(why).toContainText("Can be reached");
  for (const code of ["usual_service", "best_offer", "fewer_than_3_visits", "reachable", "change_since_last"])
    await expect(why).not.toContainText(code);

  // No results, then clear.
  await page.getByTestId("patient-search").fill("nobody-has-this-name");
  await expect(page.getByRole("main").getByText("No patients match these filters")).toBeVisible();
  await expect(tid(page, "result-count")).toHaveText("0 patients match");
  await tid(page, "clear-filters").click();
  await expect(page.getByTestId("patient-search")).toBeFocused();
  await expect(page.getByTestId("patient-search")).toHaveValue("");
  await expect(tid(page, "result-count")).toHaveText("58 patients");

  // Reachable only.
  await page.getByTestId("reachable-only").check();
  await expect(page).toHaveURL(/reachable=1/);
  await expect(tid(page, "result-count")).toContainText("patients match");
  const reachableCount = Number((await tid(page, "result-count").innerText()).match(/^(\d+)/)![1]);
  expect(reachableCount).toBeGreaterThan(0);
  expect(reachableCount).toBeLessThan(58);
  await expect(rowsOf(page).filter({ hasText: "Not reachable" })).toHaveCount(0);

  // A typed page has no status filter.
  await expect(page.getByTestId("status-filter")).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("type-saved-1440.png"), fullPage: true });
});

test("saved mode: a linked URL restores the same view", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.goto("/reactivation/types/lapsed_regular?sort=value&dir=asc&reachable=1&page=1");
  await expect(tid(page, "sort-value").locator("..")).toHaveAttribute("aria-sort", "ascending");
  await expect(tid(page, "reachable-only")).toBeChecked();
  await expect(tid(page, "sort-direction")).toHaveText("Lowest first");
  await expect(tid(page, "result-count")).toContainText("patients match");
});

test("the Unclassified page is the only one with a status filter, and defaults to dormant", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.goto("/reactivation/types/unclassified");
  await expect(tid(page, "result-count")).toHaveText("6 patients");
  await expect(tid(page, "summary-worth")).toContainText("Not sized");
  await tid(page, "summary-worth").getByTestId("not-sized").locator(".dp-hint-trigger").focus();
  await expect(tid(page, "summary-worth").getByRole("tooltip")).toContainText("don't fit any patient type");
  await page.getByTestId("status-filter").selectOption("at_risk");
  await expect(page).toHaveURL(/status=at_risk/);
  await expect(tid(page, "result-count")).toHaveText("18 patients match");
  await expect(rowsOf(page).first()).toContainText("At risk");
  await expect(rowsOf(page).first()).toContainText("Not sized");
  await page.getByTestId("status-filter").selectOption("all");
  await expect(tid(page, "result-count")).toHaveText("24 patients match");
});

test("a type whose data isn't there explains why and what to do, and a paid-up type says so", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.goto("/reactivation/types/churned_member");
  const card = tid(page, "type-unavailable");
  await expect(card).toContainText("Not available for this clinic");
  await expect(card).toContainText("No membership records have been imported.");
  await expect(card).toContainText("What you can do");
  await expect(card.getByRole("link", { name: "Go to Import data" })).toBeVisible();
  await expect(tid(page, "patients-table")).toHaveCount(0);

  await page.goto("/reactivation/types/unused_balance");
  await expect(tid(page, "summary-worth")).toContainText("$6,400");
  await expect(tid(page, "summary-worth")).toContainText("Already paid");
  await expect(rowsOf(page).first()).toContainText("already paid");
  await page.goto("/reactivation/types/not_a_type");
  await expect(page.getByRole("main")).toContainText("That group doesn't exist");
});

test("front desk sees the totals but not the patients, and the patients endpoint is never called", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  helper("front-desk", workspace);
  const calls: string[] = [];
  page.on("request", (r) => calls.push(r.url()));
  await page.goto("/reactivation/types/overdue_maintenance");
  await expect(tid(page, "no-role")).toContainText("for clinic owners and office managers");
  await expect(tid(page, "summary-patients")).toContainText("58");
  await expect(tid(page, "patients-table")).toHaveCount(0);
  expect(calls.filter((u) => u.includes("/patients"))).toEqual([]);
});

test("an error can be retried", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  // Fail every request until told otherwise: in development React runs an effect twice, so "fail once" would be
  // used up by the first, discarded request.
  let failing = true;
  await page.route("**/runs/*/patients*", async (route) => {
    if (failing) return route.abort();
    await route.continue();
  });
  await page.goto("/reactivation/types/overdue_maintenance");
  const alert = page.getByRole("main").getByRole("alert");
  await expect(alert).toContainText("We couldn't load the patients.");
  failing = false;
  await alert.getByRole("button", { name: "Try again" }).click();
  await expect(rowsOf(page)).toHaveCount(25);
});

test("a run in progress is mentioned while the last results stay usable", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.goto("/reactivation");
  await tid(page, "run-now").click();
  await expect(tid(page, "progress-card")).toBeVisible();
  await page.goto("/reactivation/types/overdue_maintenance");
  await expect(page.getByRole("main").getByText("A new analysis is running.")).toBeVisible();
  await expect(rowsOf(page)).toHaveCount(25);
});

test("the table works from the keyboard", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.goto("/reactivation/types/overdue_maintenance");
  await expect(rowsOf(page)).toHaveCount(25);

  // Sorting from the header refetches the list. Wait until that has finished and the rows are the new ones,
  // so the next keystrokes land on rows that will not be swapped out underneath them.
  const sorted = page.waitForResponse((r) => r.url().includes("/patients") && r.url().includes("sort=overdue"));
  await tid(page, "sort-overdue").focus();
  await page.keyboard.press("Enter");
  await sorted;
  await expect(tid(page, "sort-overdue").locator("..")).toHaveAttribute("aria-sort", "descending");
  await expect(tid(page, "patients-table")).toHaveAttribute("aria-busy", "false");
  await expect(rowsOf(page)).toHaveCount(25);

  // Then follow one patient, by name, so nothing but their own row matters.
  const name = (await rowsOf(page).first().getByTestId("expand-row").innerText()).trim();
  const toggle = rowsOf(page).filter({ hasText: name }).getByTestId("expand-row");
  await toggle.focus();
  await page.keyboard.press("Enter");
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Enter");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
});

test("one change to the list makes one request, and an open row stays open while the data refreshes", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.goto("/reactivation/types/overdue_maintenance");
  await expect(rowsOf(page)).toHaveCount(25);
  await expect(tid(page, "patients-table")).toHaveAttribute("aria-busy", "false");

  const name = (await rowsOf(page).first().getByTestId("expand-row").innerText()).trim();
  await rowsOf(page).first().getByTestId("expand-row").click();
  await expect(rowsOf(page).first().getByTestId("expand-row")).toHaveAttribute("aria-expanded", "true");

  const requests: string[] = [];
  page.on("request", (r) => r.url().includes("/patients") && requests.push(r.url()));
  await page.getByTestId("reachable-only").check();
  await expect(page).toHaveURL(/reachable=1/);
  await expect(tid(page, "patients-table")).toHaveAttribute("aria-busy", "false");
  await page.waitForTimeout(500); // long enough for any duplicate request to show up
  expect(requests, "one filter change, one request").toHaveLength(1);
  expect(requests[0]).toContain("reachable=true");

  // The patient who was open is still open if they are still in the list.
  const same = rowsOf(page).filter({ hasText: name });
  if ((await same.count()) > 0)
    await expect(same.getByTestId("expand-row")).toHaveAttribute("aria-expanded", "true");
});

test("narrow screens turn rows into cards with no sideways scroll", async ({ page }, info) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.goto("/reactivation/types/overdue_maintenance");
  await expect(rowsOf(page)).toHaveCount(25);
  await page.setViewportSize({ width: 1440, height: 1000 });
  expect(await rowsOf(page).first().evaluate((e) => getComputedStyle(e).display)).toBe("table-row");
  await noHorizontalScroll(page);
  await page.setViewportSize({ width: 768, height: 1000 });
  await expect(async () => {
    expect(await rowsOf(page).first().evaluate((e) => getComputedStyle(e).display)).toBe("grid");
  }).toPass();
  await noHorizontalScroll(page);
  await rowsOf(page).first().getByTestId("expand-row").click();
  await expect(tid(page, "why-row").first()).toBeVisible();
  await noHorizontalScroll(page);
  await page.screenshot({ path: info.outputPath("type-saved-768.png"), fullPage: true });
});

test("file mode: the type page reads the file results in the browser, makes no request, and a refresh falls back", async ({ page }, info) => {
  helper("seed", workspace, ["--scenario", "empty"]);
  await page.goto("/reactivation");
  await tid(page, "import-csv").click();
  await page.getByTestId("csv-file-input").setInputFiles(csvFile(60));
  await expect(tid(page, "csv-banner")).toContainText("Showing results from export.csv.", { timeout: 60_000 });

  await tid(page, "type-row-lapsed_regular").getByRole("link").click();
  await expect(page).toHaveURL(/\/reactivation\/types\/lapsed_regular\?source=file$/);
  await expect(tid(page, "csv-banner")).toContainText("This data is not saved. Refreshing the page clears it.");
  await expect(tid(page, "type-title")).toContainText("from file");
  await expect(tid(page, "csv-frame")).toBeVisible();
  await expect(rowsOf(page).first()).toBeVisible();

  // From here on, nothing may go to the server.
  const calls: string[] = [];
  page.on("request", (r) => {
    if (/\/api\/|csv-analysis/.test(r.url())) calls.push(r.url());
  });
  const total = Number((await tid(page, "result-count").innerText()).match(/^(\d+)/)![1]);
  expect(total).toBeGreaterThan(25);
  await tid(page, "page-next").click();
  await expect(tid(page, "page-number")).toContainText("Page 2");
  expect(page.url()).toMatch(/\?source=file$/); // file mode keeps its controls out of the URL
  await tid(page, "sort-value").click();
  await expect(tid(page, "sort-value").locator("..")).toHaveAttribute("aria-sort", "descending");
  await expect(tid(page, "page-number")).toContainText("Page 1");
  await page.getByTestId("patient-search").fill("person 07");
  await expect(rowsOf(page)).toHaveCount(1);
  await expect(rowsOf(page).first()).toContainText("Person 07");
  await rowsOf(page).first().getByTestId("expand-row").click();
  await expect(tid(page, "why-row").first()).toContainText("Needs visit times");
  await expect(tid(page, "why-row").first()).toContainText("Botox, their usual service");
  await page.getByTestId("patient-search").fill("p6"); // the id used in the file
  await expect(rowsOf(page).first()).toBeVisible();
  await page.getByTestId("reachable-only").check();
  await expect(tid(page, "result-count")).toContainText("match");
  await page.screenshot({ path: info.outputPath("type-file-1440.png"), fullPage: true });
  expect(calls).toEqual([]);

  // A full page load clears the file results, so the welcome page is back.
  await page.goto("/reactivation");
  await expect(page.getByRole("main")).toContainText("Upload your data to find your dormant patients");
});

test("file mode: a refresh sends the user back to the Overview with a clear message", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "empty"]);
  await page.goto("/reactivation");
  await tid(page, "import-csv").click();
  await page.getByTestId("csv-file-input").setInputFiles(csvFile(40));
  await expect(tid(page, "csv-banner")).toContainText("export.csv", { timeout: 60_000 });
  await tid(page, "type-row-lapsed_regular").getByRole("link").click();
  await expect(page).toHaveURL(/source=file$/);
  await expect(rowsOf(page).first()).toBeVisible();

  await page.reload();
  await expect(page).toHaveURL(/\/reactivation$/);
  const notice = page.getByRole("main").getByText("Your file results were cleared.");
  await expect(notice).toBeVisible();
  await expect(page.getByRole("main")).toContainText("Nothing from the file was saved.");
  await expect(tid(page, "csv-banner")).toHaveCount(0);
  await expect(tid(page, "import-csv")).toBeVisible(); // a way to import again
});

test("file mode: a type the file can't measure says so in the file's words", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "empty"]);
  await page.goto("/reactivation");
  await tid(page, "import-csv").click();
  await page.getByTestId("csv-file-input").setInputFiles(csvFile(30));
  await expect(tid(page, "csv-banner")).toContainText("export.csv", { timeout: 60_000 });
  await tid(page, "type-row-consult_not_converted").getByRole("link").click();
  const card = tid(page, "type-unavailable");
  await expect(card).toContainText("Not available from this file");
  await expect(card).toContainText("visit_type");
  await expect(card).not.toContainText("for this clinic");
  await expect(tid(page, "summary-worth")).toContainText("Not available from this file");
  await expect(tid(page, "patients-table")).toHaveCount(0);
});

test("a saved page reached while file results are open says so, and Back lands on the saved overview", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.goto("/reactivation");
  await tid(page, "import-csv").click();
  await page.getByTestId("csv-file-input").setInputFiles(csvFile(30));
  await expect(tid(page, "csv-banner")).toContainText("export.csv", { timeout: 60_000 });
  // A client-side navigation to a saved URL (a full load would clear the file results).
  await page.evaluate(() =>
    (window as unknown as { next: { router: { push: (u: string) => void } } }).next.router.push(
      "/reactivation/types/overdue_maintenance",
    ),
  );
  await expect(page).toHaveURL(/\/overdue_maintenance$/);
  await expect(page.getByRole("main").getByText("File results are also open in this tab.")).toBeVisible();
  await expect(tid(page, "type-summary")).toContainText("58"); // saved numbers, not the file's
  await page.getByRole("link", { name: "← Back to overview" }).click();
  await expect(page).toHaveURL(/view=saved/);
  await expect(tid(page, "last-analysed")).toContainText("Last analysed");
  await tid(page, "view-file-results").click();
  await expect(tid(page, "csv-banner")).toContainText("export.csv");
});
