import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import { resolve, dirname } from "node:path";
import { test, expect, type Download, type Page } from "@playwright/test";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../../../..");
const script = "packages/features/reactivation/scripts/browser_seed.py";
const reader = "packages/features/reactivation/scripts/read_report.py";

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
  workspace = `Export ${randomUUID().slice(0, 8)}`;
  await signIn(page, workspace);
});
test.afterEach(() => {
  helper("cleanup", workspace);
});

type Sheet = { name: string; freeze: string | null; rows: (string | number | null)[][] };
const main = (page: Page) => page.getByRole("main");
const tid = (page: Page, id: string) => main(page).getByTestId(id);

/** Saves the download and reads it back with openpyxl, a reader written by other people. */
async function readReport(download: Download, info: { outputPath: (n: string) => string }) {
  const path = info.outputPath(`report-${randomUUID().slice(0, 6)}.xlsx`);
  await download.saveAs(path);
  const out = execFileSync("uv", ["run", "python", reader, path], { cwd: repoRoot, encoding: "utf8", env: process.env });
  return JSON.parse(out.trim().split("\n").pop()!).sheets as Sheet[];
}

const labelled = (rows: Sheet["rows"], label: string) => rows.find((r) => r[0] === label);
const toNumber = (text: string) => Number(text.replace(/[^0-9]/g, ""));

/** What the Overview shows for each patient type, read from the page: label, count (null when not available). */
async function onScreen(page: Page) {
  const rows = tid(page, "types-table").locator('tr[data-testid^="type-row-"]');
  const out: { label: string; count: number | null }[] = [];
  for (let i = 0; i < (await rows.count()); i++) {
    const cells = rows.nth(i).locator("td");
    const label = (await cells.nth(0).locator("strong, a").first().innerText()).trim();
    const text = (await cells.nth(1).innerText()).trim();
    out.push({ label, count: /^[\d,]+$/.test(text) ? toNumber(text) : null });
  }
  return out;
}

/** The report must agree with the screen: totals as the tiles show them, and every group's patients as counted there. */
async function expectReportMatchesScreen(page: Page, sheets: Sheet[]) {
  const summary = sheets[0]!;
  expect(summary.name).toBe("Summary");
  expect(summary.rows[0]![0]).toBe("Dormant patients report");
  const dormantTile = await tid(page, "tile-dormant").innerText();
  const [tileDormant, tileTotal] = [...dormantTile.matchAll(/[\d,]+/g)].map((m) => toNumber(m[0]));
  expect(labelled(summary.rows, "Dormant patients")![1]).toBe(tileDormant);
  expect(labelled(summary.rows, "Patients analysed")![1]).toBe(tileTotal);

  const screen = await onScreen(page);
  let inSheets = 0;
  for (const { label, count } of screen) {
    const line = labelled(summary.rows.slice(14), label)!;
    expect(line, `${label} is listed in the summary`).toBeTruthy();
    if (count === null) {
      expect(line[1]).toBe("Not available");
      continue;
    }
    expect(line[1], `${label}: patients in the summary`).toBe(count);
    if (count === 0) continue;
    const sheet = sheets.find((s) => s.name === line[5])!;
    expect(sheet, `${label} has its own sheet`).toBeTruthy();
    expect(sheet.rows[0]![0]).toBe(label); // the heading
    expect(sheet.rows[2]![0]).toBe(`${count} ${count === 1 ? "patient" : "patients"}`);
    expect(sheet.rows[4]![0]).toBe("Patient"); // the column headings
    const patients = sheet.rows.slice(5).filter((r) => r[0] !== null);
    expect(patients.length, `${label}: patient lines`).toBe(count);
    expect(sheet.freeze).toBe("A6");
    inSheets += patients.length;
  }
  expect(inSheets, "every dormant patient is in exactly one group").toBe(tileDormant);
  return { tileDormant: tileDormant!, screen };
}

const day = (daysAgo: number) => new Date(Date.now() - daysAgo * 86_400_000).toISOString().slice(0, 10);
function csvFile(patients: number, recent = false) {
  const lines = ["patient_id,patient_name,email,phone,sms_consent,visit_date,line_kind,service_name,service_category,amount"];
  for (let i = 0; i < patients; i++) {
    const last = recent ? 3 + (i % 10) : 200 + ((i * 17) % 500);
    for (let k = 0; k < 3; k++)
      lines.push(
        [`P${i}`, `Person ${i}`, `p${i}@example.test`, `555010${String(i).padStart(4, "0")}`, "yes", day(last + 60 * k), "service", i % 2 ? "Botox" : "Facial", i % 2 ? "Injectables" : "Facials", `${150 + i * 7}.00`].join(","),
      );
  }
  return { name: "march-export.csv", mimeType: "text/csv", buffer: Buffer.from(lines.join("\n") + "\n") };
}

async function importFile(page: Page, file: ReturnType<typeof csvFile>) {
  await page.goto("/reactivation/import");
  await expect(page.getByTestId("csv-choose")).toBeFocused(); // hydrated
  await page.getByTestId("csv-file-input").setInputFiles(file);
  await expect(tid(page, "csv-banner")).toContainText("march-export.csv", { timeout: 60_000 });
}

test("a saved analysis exports as a workbook that agrees with the screen, in one request", async ({ page }, info) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.goto("/reactivation");
  await expect(tid(page, "tile-dormant")).toBeVisible();
  const calls: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/features/reactivation/")) calls.push(`${r.method()} ${new URL(r.url()).pathname}`);
  });

  const [download] = await Promise.all([page.waitForEvent("download"), tid(page, "export-report").click()]);
  expect(download.suggestedFilename()).toMatch(/^dormant-patients-report-\d{4}-\d{2}-\d{2}-saved\.xlsx$/);
  const sheets = await readReport(download, info);

  const summary = sheets[0]!.rows;
  expect(labelled(summary, "Clinic")![1]).toBe(workspace);
  expect(String(labelled(summary, "Source")![1])).toMatch(/^Saved analysis from \d{4}-\d{2}-\d{2}$/);
  expect(String(labelled(summary, "Note")![1])).toContain("patient names");
  expect(labelled(summary, "Report date")![1]).toBe(download.suggestedFilename().match(/\d{4}-\d{2}-\d{2}/)![0]);
  const { tileDormant } = await expectReportMatchesScreen(page, sheets);
  expect(tileDormant).toBeGreaterThan(0);

  // one call fetched the whole report; the paged patient list was not used 100 rows at a time
  expect(calls.filter((c) => c.includes("/report"))).toHaveLength(1);
  expect(calls.filter((c) => c.includes("/patients"))).toEqual([]);
  await expect(tid(page, "export-report")).toHaveText("Export report");
  await expect(tid(page, "export-error")).toHaveCount(0);
});

test("file results export from memory: no request leaves the page, the console stays quiet, and the file says it is not saved", async ({ page }, info) => {
  helper("seed", workspace, ["--scenario", "empty"]);
  await importFile(page, csvFile(25));
  const seen: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/")) seen.push(`${r.method()} ${r.url()} ${r.postData() ?? ""}`);
  });
  page.on("console", (m) => seen.push(`console ${m.type()} ${m.text()}`));

  const [download] = await Promise.all([page.waitForEvent("download"), tid(page, "export-report").click()]);
  expect(download.suggestedFilename()).toMatch(/^dormant-patients-report-\d{4}-\d{2}-\d{2}-from-file\.xlsx$/);
  expect(download.suggestedFilename()).not.toContain("march-export"); // the file's own name stays out of the name
  const sheets = await readReport(download, info);
  expect(labelled(sheets[0]!.rows, "Source")![1]).toBe("File march-export.csv, not saved");
  await expectReportMatchesScreen(page, sheets);
  const someone = sheets.flatMap((s) => s.rows).find((r) => String(r[0]).startsWith("Person "));
  expect(someone, "patient names from the file are in the report").toBeTruthy();

  expect(seen, "nothing was sent and nothing was logged").toEqual([]);
  await expect(page.getByTestId("mode-badge")).toHaveText("From file");
});

test("with no dormant patients there is nothing to export, and it says so", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "empty"]);
  await importFile(page, csvFile(12, true)); // everyone visited in the last two weeks
  await expect(tid(page, "tile-dormant")).toContainText("0");
  await expect(tid(page, "export-report")).toHaveAttribute("aria-disabled", "true");
  await expect(tid(page, "export-empty")).toHaveText("No patients to export");
  let downloaded = false;
  page.on("download", () => (downloaded = true));
  await tid(page, "export-report").click({ force: true });
  await page.waitForTimeout(500);
  expect(downloaded).toBe(false);
});

test("front desk has no Export report button", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.route("**/api/v1/auth/me", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    for (const m of body.memberships) m.role = "front_desk";
    await route.fulfill({ response, json: body });
  });
  await page.goto("/reactivation");
  await expect(tid(page, "tile-dormant")).toBeVisible();
  await expect(tid(page, "export-report")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Export report/ })).toHaveCount(0);
});

test("while the report builds the button says so and ignores a second press, and a failure can be retried", async ({ page }, info) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.goto("/reactivation");
  await expect(tid(page, "tile-dormant")).toBeVisible();
  let calls = 0;
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  await page.route("**/runs/*/report", async (route) => {
    calls++;
    await gate;
    await route.continue();
  });
  const button = tid(page, "export-report");
  await button.click();
  await expect(button).toHaveText("Building report…");
  await expect(button).toHaveAttribute("aria-disabled", "true");
  await expect(button).toHaveAttribute("aria-busy", "true");
  await button.click({ force: true }); // a second press while it builds does nothing
  const [download] = await Promise.all([page.waitForEvent("download"), Promise.resolve(release())]);
  expect(calls).toBe(1);
  await readReport(download, info);
  await expect(button).toHaveText("Export report");

  // a failed request shows a plain message, and pressing again works
  await page.unroute("**/runs/*/report");
  await page.route("**/runs/*/report", (route) => route.fulfill({ status: 500, body: "{}" }));
  await button.click();
  await expect(tid(page, "export-error")).toHaveText("We couldn't build the report. Please try again.");
  await expect(tid(page, "export-error")).toHaveAttribute("role", "alert");
  await expect(button).toHaveText("Export report");
  await page.unroute("**/runs/*/report");
  const [again] = await Promise.all([page.waitForEvent("download"), button.click()]);
  expect(again.suggestedFilename()).toMatch(/-saved\.xlsx$/);
  await expect(tid(page, "export-error")).toHaveCount(0);
});

test("on a 360 px screen the button fits, nothing scrolls sideways, and the keyboard can export", async ({ page }, info) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.setViewportSize({ width: 360, height: 900 });
  await page.goto("/reactivation");
  await expect(tid(page, "tile-dormant")).toBeVisible();
  const button = tid(page, "export-report");
  await expect(button).toBeVisible();
  const box = (await button.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(360);
  expect(box.height).toBeGreaterThanOrEqual(40);
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(over, "the page should not scroll sideways").toBeLessThanOrEqual(1);

  await button.focus();
  const [download] = await Promise.all([page.waitForEvent("download"), page.keyboard.press("Enter")]);
  const sheets = await readReport(download, info);
  expect(sheets[0]!.name).toBe("Summary");
});
