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
  workspace = `FileView ${randomUUID().slice(0, 8)}`;
  await signIn(page, workspace);
  helper("seed", workspace, ["--scenario", "empty"]);
});
test.afterEach(() => {
  helper("cleanup", workspace);
});

const tid = (page: Page, id: string) => page.getByRole("main").getByTestId(id);
const dataNav = (page: Page) => page.getByRole("navigation", { name: "Dormant patients data" });
const viewerLink = (page: Page) => dataNav(page).getByRole("link", { name: "Imported file" });

const COLUMNS = ["patient_id", "patient_name", "email", "phone", "sms_consent", "visit_date", "line_kind", "service_name", "service_category", "amount"];
const day = (daysAgo: number) => new Date(Date.now() - daysAgo * 86_400_000).toISOString().slice(0, 10);
function csvFile(patients: number, extraRows = 0) {
  const lines = [COLUMNS.join(",")];
  for (let i = 0; i < patients; i++) {
    const last = 200 + ((i * 17) % 500);
    for (let k = 0; k < 3; k++)
      lines.push(
        [`P${i}`, `Person ${i}`, `p${i}@example.test`, `555010${String(i).padStart(4, "0")}`, "yes", day(last + 60 * k), "service", i % 2 ? "Botox" : "Facial", i % 2 ? "Injectables" : "Facials", `${150 + i * 7}.00`].join(","),
      );
  }
  for (let i = 0; i < extraRows; i++)
    lines.push(`P${i % patients},Person ${i % patients},p${i % patients}@example.test,555010${String(i % patients).padStart(4, "0")},yes,${day(300)},product,SPF 50,Skincare,${20 + (i % 50)}.00`);
  return { name: "march-export.csv", mimeType: "text/csv", buffer: Buffer.from(lines.join("\n") + "\n") };
}

/** Imports through the Import data page and waits for the Overview in file mode. */
async function importFile(page: Page, file: ReturnType<typeof csvFile>) {
  await page.goto("/reactivation/import");
  // The picker takes focus once the page has hydrated; a file chosen before that is lost to React's dev double effect.
  await expect(page.getByTestId("csv-choose")).toBeFocused();
  await page.getByTestId("csv-file-input").setInputFiles(file);
  await expect(tid(page, "csv-banner")).toContainText("Showing results from march-export.csv.", { timeout: 90_000 });
}

test("after an import, the sidebar shows the file's headers and rows without importing again", async ({ page }) => {
  await importFile(page, csvFile(40));
  // A marker on the window proves the page was not reloaded, so the file is still the one in memory.
  await page.evaluate(() => ((window as unknown as { __stay: number }).__stay = 1));
  const analyses: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("csv-analysis")) analyses.push(r.url());
  });

  await viewerLink(page).click();
  await expect(page).toHaveURL(/\/reactivation\/file$/);
  await expect(viewerLink(page)).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("heading", { level: 1, name: /Imported file/ })).toBeVisible();
  await expect(tid(page, "file-meta")).toContainText("march-export.csv · 120 rows · imported");
  await expect(tid(page, "file-privacy")).toContainText("Shown only in this tab. Nothing is saved or sent. Refreshing the page clears it.");

  const table = tid(page, "file-table");
  await expect(table.locator("thead th")).toHaveText(["Row", ...COLUMNS]);
  const rows = tid(page, "file-row");
  await expect(rows).toHaveCount(50);
  await expect(rows.first().locator("th, td")).toHaveText(["2", "P0", "Person 0", "p0@example.test", "5550100000", "yes", /^\d{4}-\d\d-\d\d$/, "service", "Facial", "Facials", "150.00"]);
  await expect(rows.nth(3).locator("th, td").nth(2)).toHaveText("Person 1"); // three rows a patient
  await expect(tid(page, "file-range")).toHaveText("Showing 1 to 50 of 120 rows");
  await expect(tid(page, "file-region")).toHaveAccessibleName("Rows of march-export.csv");

  expect(await page.evaluate(() => (window as unknown as { __stay: number }).__stay)).toBe(1);
  expect(analyses).toEqual([]);
});

test("the table pages by rows per page, and works from the keyboard", async ({ page }) => {
  await importFile(page, csvFile(40));
  await viewerLink(page).click();
  await expect(tid(page, "file-range")).toHaveText("Showing 1 to 50 of 120 rows");
  await expect(tid(page, "file-page")).toHaveText("Page 1 of 3");
  await expect(tid(page, "file-prev")).toHaveAttribute("aria-disabled", "true");

  // the keyboard: focus Next, press Enter, and focus stays on the button
  await tid(page, "file-next").focus();
  await page.keyboard.press("Enter");
  await expect(tid(page, "file-range")).toHaveText("Showing 51 to 100 of 120 rows");
  await expect(tid(page, "file-next")).toBeFocused();
  await expect(tid(page, "file-row").first().locator("th")).toHaveText("52"); // the line the row starts on

  await tid(page, "file-last").click();
  await expect(tid(page, "file-range")).toHaveText("Showing 101 to 120 of 120 rows");
  await expect(tid(page, "file-row")).toHaveCount(20);
  await expect(tid(page, "file-next")).toHaveAttribute("aria-disabled", "true");
  await tid(page, "file-next").click({ force: true }); // aria-disabled: pressing it does nothing and loses nothing
  await expect(tid(page, "file-range")).toHaveText("Showing 101 to 120 of 120 rows");

  await tid(page, "file-size").selectOption("25");
  await expect(tid(page, "file-range")).toHaveText("Showing 101 to 120 of 120 rows");
  await expect(tid(page, "file-page")).toHaveText("Page 5 of 5");
  await tid(page, "file-first").click();
  await expect(tid(page, "file-range")).toHaveText("Showing 1 to 25 of 120 rows");
  await tid(page, "file-size").selectOption("100");
  await expect(tid(page, "file-row")).toHaveCount(100);

  // the scroll area is reachable and named, so it can be scrolled with the keyboard
  await expect(tid(page, "file-region")).toHaveAttribute("tabindex", "0");
  await expect(page.getByRole("region", { name: "Rows of march-export.csv" })).toBeVisible();
});

test("with no file, the page says so and links to Import data; a refresh clears an imported file", async ({ page }) => {
  await page.goto("/reactivation");
  await expect(viewerLink(page)).toBeVisible(); // visible before any import
  await viewerLink(page).click();
  await expect(tid(page, "file-empty")).toContainText("No file imported yet");
  await expect(tid(page, "file-empty")).toContainText("Import a CSV file and its rows will show here.");
  await tid(page, "file-import-link").click();
  await expect(page).toHaveURL(/\/reactivation\/import$/);

  await page.getByTestId("csv-file-input").setInputFiles(csvFile(20));
  await expect(tid(page, "csv-banner")).toContainText("march-export.csv", { timeout: 60_000 });
  await viewerLink(page).click();
  await expect(tid(page, "file-table")).toBeVisible();
  await page.reload();
  await expect(tid(page, "file-empty")).toBeVisible();
});

test("the rows stay in this tab: no request, storage, console line or URL carries them", async ({ page }) => {
  await importFile(page, csvFile(20));
  const seen: string[] = [];
  page.on("request", (r) => seen.push(`${r.method()} ${r.url()} ${r.postData() ?? ""}`));
  page.on("console", (m) => seen.push(`console ${m.text()}`));

  await viewerLink(page).click();
  await expect(tid(page, "file-table")).toBeVisible();
  await tid(page, "file-next").click();
  await tid(page, "file-size").selectOption("25");

  expect(page.url()).not.toMatch(/Person|march|example/);
  expect(seen.filter((line) => /Person|example\.test|5550100/.test(line))).toEqual([]);
  const stored = await page.evaluate(() => JSON.stringify([{ ...localStorage }, { ...sessionStorage }, document.cookie]));
  expect(stored).not.toMatch(/Person|example\.test|march-export/);
});

test("front desk has no Imported file item, and the page refuses them by URL", async ({ page }) => {
  await page.route("**/api/v1/auth/me", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    for (const m of body.memberships) m.role = "front_desk";
    await route.fulfill({ response, json: body });
  });
  await page.goto("/reactivation");
  await expect(page.getByRole("link", { name: "Imported file" })).toHaveCount(0);
  await page.goto("/reactivation/file");
  await expect(tid(page, "file-refused")).toContainText("Only an owner or office manager can import files.");
  await expect(tid(page, "file-table")).toHaveCount(0);
});

test("on a narrow screen the table scrolls inside its own region, not the page", async ({ page }) => {
  await importFile(page, csvFile(40));
  await page.setViewportSize({ width: 768, height: 1000 });
  await page.getByRole("button", { name: "Menu" }).click(); // at this width the sidebar is a menu
  await viewerLink(page).click();
  await expect(tid(page, "file-table")).toBeVisible();
  const { page: pageOver, region } = await page.evaluate(() => {
    const r = document.querySelector('[data-testid="file-region"]') as HTMLElement;
    return { page: document.documentElement.scrollWidth - window.innerWidth, region: r.scrollWidth - r.clientWidth };
  });
  expect(pageOver, "the page should not scroll sideways").toBeLessThanOrEqual(1);
  expect(region, "the table scrolls inside its region").toBeGreaterThan(0);
});

test("a large file opens quickly and pages to its last row", async ({ page }) => {
  test.setTimeout(180_000);
  await importFile(page, csvFile(3000, 130_000)); // about 14 MB, 139,000 rows
  const opened = Date.now();
  await viewerLink(page).click();
  await expect(tid(page, "file-range")).toHaveText("Showing 1 to 50 of 139,000 rows");
  expect(Date.now() - opened, "the viewer opens within a few seconds").toBeLessThan(5000);
  await tid(page, "file-last").click();
  await expect(tid(page, "file-range")).toHaveText("Showing 138,951 to 139,000 of 139,000 rows");
  await expect(tid(page, "file-row").last().locator("th")).toHaveText("139001");
});
