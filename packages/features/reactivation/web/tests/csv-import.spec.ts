import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve, dirname } from "node:path";
import { test, expect, type Page } from "@playwright/test";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../../../..");
const script = "packages/features/reactivation/scripts/browser_seed.py";

type Facts = { dormant: number; total: number };

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
  await page.getByRole("button", { name: "Create workspace", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
}

let workspace: string;
test.beforeEach(async ({ page }) => {
  workspace = `Import ${randomUUID().slice(0, 8)}`;
  await signIn(page, workspace);
});
test.afterEach(() => {
  helper("cleanup", workspace);
});

const tid = (page: Page, id: string) => page.getByRole("main").getByTestId(id);

async function noHorizontalScroll(page: Page) {
  const over = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(over, "the page should not scroll sideways").toBeLessThanOrEqual(1);
}

const day = (daysAgo: number) =>
  new Date(Date.now() - daysAgo * 86_400_000).toISOString().slice(0, 10);

/** Patients with three visits each, the last one 200 to 700 days ago, so most of them are dormant. */
function csvFile(patients: number, extraRows = 0) {
  const lines = ["patient_id,patient_name,email,phone,sms_consent,visit_date,line_kind,service_name,service_category,amount"];
  for (let i = 0; i < patients; i++) {
    const last = 200 + ((i * 17) % 500);
    for (let k = 0; k < 3; k++) {
      lines.push(
        [
          `P${i}`, `Person ${i}`, `p${i}@example.test`, `555010${String(i).padStart(4, "0")}`, "yes",
          day(last + 60 * k), "service", i % 2 ? "Botox" : "Facial", i % 2 ? "Injectables" : "Facials",
          `${150 + i * 7}.00`,
        ].join(","),
      );
    }
  }
  for (let i = 0; i < extraRows; i++)
    lines.push(`P${i % patients},Person ${i % patients},p${i % patients}@example.test,555010${String(i % patients).padStart(4, "0")},yes,${day(300)},product,SPF 50,Skincare,${20 + (i % 50)}.00`);
  return Buffer.from(lines.join("\n") + "\n");
}

const file = (name: string, buffer: Buffer) => ({ name, mimeType: "text/csv", buffer });

test("a clinic with no data lands on the welcome page and can read the guide and get the template", async ({ page }, info) => {
  helper("seed", workspace, ["--scenario", "empty"]);
  await page.goto("/reactivation");

  await expect(
    page.getByRole("heading", { level: 1, name: "Upload your data to find your dormant patients" }),
  ).toBeVisible();
  await expect(tid(page, "import-csv")).toBeVisible();
  await expect(tid(page, "tile-dormant")).toHaveCount(0);
  // The importer lives on this page only: not in the sidebar, and the platform's own import page is untouched.
  await expect(page.getByRole("navigation").getByRole("link", { name: "Import CSV" })).toHaveCount(0);

  const download = page.waitForEvent("download");
  await tid(page, "download-template").click();
  const saved = await download;
  expect(saved.suggestedFilename()).toBe("dormant-patients-template.csv");
  const text = readFileSync((await saved.path())!, "utf8");
  expect(text.split("\n")[0]).toContain("patient_id,patient_name");
  expect(text.trim().split("\n")).toHaveLength(4); // header plus three example rows

  // The guide is collapsed until opened, and is generated from the API's column list.
  const help = tid(page, "csv-help");
  await expect(help).not.toHaveAttribute("open", "");
  await help.getByText("What should my file look like?").click();
  await expect(tid(page, "csv-columns").locator("tbody tr")).toHaveCount(21);
  await expect(help).toContainText("membership_monthly_fee");
  await expect(help).toContainText("only for a service or product line with an amount of 0 or more");
  await expect(help).toContainText("Allowed: service, product, membership, package, other");

  for (const width of [1440, 768]) {
    await page.setViewportSize({ width, height: 1000 });
    await noHorizontalScroll(page);
    await page.screenshot({ path: info.outputPath(`welcome-${width}.png`), fullPage: true });
  }
});

test("importing a file shows its results with a banner, keeps them across pages, and a refresh clears them", async ({ page }, info) => {
  helper("seed", workspace, ["--scenario", "empty"]);
  await page.goto("/reactivation");

  await tid(page, "import-csv").click();
  await expect(page.getByTestId("csv-choose")).toBeFocused(); // keyboard users land on the control
  await page.getByTestId("csv-file-input").setInputFiles(file("march-export.csv", csvFile(40)));

  const banner = tid(page, "csv-banner");
  await expect(banner).toContainText("Showing results from march-export.csv.", { timeout: 60_000 });
  await expect(banner).toContainText("This data is not saved. Refreshing the page clears it.");
  await expect(page.getByRole("heading", { level: 1 })).toBeFocused();
  await expect(page.getByTestId("csv-live")).toContainText("Analysis of march-export.csv is ready");
  await expect(tid(page, "tile-dormant")).toContainText("of 40 patients");
  await expect(tid(page, "tile-change")).toContainText("From your file");
  await expect(tid(page, "tile-change")).toContainText("120 rows");
  await expect(page.getByRole("main")).toContainText("Return rates are assumed.");
  await expect(tid(page, "type-row-unclassified")).toBeVisible();
  const consult = tid(page, "type-row-consult_not_converted");
  await expect(consult).toContainText("Not available from this file");
  await expect(consult).not.toContainText("for this clinic");
  await expect(consult).toContainText("The file has no consult visits");
  await expect(tid(page, "run-now")).toHaveCount(0);

  const about = tid(page, "about-data");
  await about.getByText(/About this data/).click();
  await expect(about).toContainText("Files don't include visit times");
  await expect(about).not.toContainText("p1@example.test"); // contact details are never returned
  for (const width of [1440, 768]) {
    await page.setViewportSize({ width, height: 1000 });
    await noHorizontalScroll(page);
    await page.screenshot({ path: info.outputPath(`file-results-${width}.png`), fullPage: true });
  }

  // The results survive moving around the section, and say so on every page.
  await tid(page, "type-row-unclassified").getByRole("link").click();
  await expect(page).toHaveURL(/\/reactivation\/types\/unclassified\?source=file$/);
  await expect(tid(page, "csv-banner")).toContainText("march-export.csv");
  const tabs = page.getByRole("navigation", { name: "Dormant patients sections" });
  await tabs.getByRole("link", { name: "Runs" }).click();
  await expect(page).toHaveURL(/\/reactivation\/runs$/);
  await tabs.getByRole("link", { name: "Overview" }).click();
  await expect(page).toHaveURL(/\/reactivation$/);
  await expect(tid(page, "csv-banner")).toContainText("march-export.csv");

  // Patient data is never put in browser storage.
  const stored = await page.evaluate(() => ({
    local: Object.keys(localStorage).length,
    session: Object.keys(sessionStorage).length,
    dumped: JSON.stringify([localStorage, sessionStorage, document.cookie]),
  }));
  expect(stored.local + stored.session).toBe(0);
  expect(stored.dumped).not.toContain("march-export");

  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Upload your data to find your dormant patients" })).toBeVisible();
  await expect(tid(page, "csv-banner")).toHaveCount(0);
});

test("a clinic with saved data sees Import CSV left of Run now, and can go back to the saved results", async ({ page }) => {
  const f = helper("seed", workspace, ["--scenario", "full"]);
  await page.goto("/reactivation");
  const importBtn = tid(page, "import-csv");
  const runBtn = tid(page, "run-now");
  const [a, b] = await Promise.all([importBtn.boundingBox(), runBtn.boundingBox()]);
  expect(a!.x + a!.width).toBeLessThanOrEqual(b!.x);
  await expect(tid(page, "tile-dormant")).toContainText(String(f.dormant));

  await importBtn.click();
  await page.getByTestId("csv-file-input").setInputFiles(file("other.csv", csvFile(25)));
  await expect(tid(page, "csv-banner")).toContainText("Showing results from other.csv.", { timeout: 60_000 });
  await expect(tid(page, "tile-dormant")).toContainText("of 25 patients");
  await expect(tid(page, "last-analysed")).toHaveCount(0);

  // A second file replaces the first.
  await tid(page, "csv-another").click();
  await page.getByTestId("csv-file-input").setInputFiles(file("second.csv", csvFile(30)));
  await expect(tid(page, "csv-banner")).toContainText("second.csv", { timeout: 60_000 });
  await expect(tid(page, "tile-dormant")).toContainText("of 30 patients");

  await tid(page, "csv-back").click();
  await expect(tid(page, "csv-banner")).toHaveCount(0);
  await expect(tid(page, "tile-dormant")).toContainText(String(f.dormant));
  await expect(tid(page, "tile-dormant")).toContainText(`of ${f.total} patients`);
  await expect(tid(page, "last-analysed")).toContainText("Last analysed");
});

test("an invalid file is rejected with a list of problems and no patient data in the message", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "empty"]);
  await page.goto("/reactivation");
  await tid(page, "import-csv").click();

  const secret = "canary.person@canary-example.test";
  const rows = Array.from({ length: 30 }, (_, i) => `P${i},Zelda Canary,${secret},2026-13-01,service,Botox,oops`);
  const bad = Buffer.from(
    "patient_id,patient_name,email,visit_date,line_kind,service_name,amount\n" + rows.join("\n") + "\n",
  );
  await page.getByTestId("csv-file-input").setInputFiles(file("broken.csv", bad));

  const errors = tid(page, "csv-errors");
  await expect(errors).toBeVisible({ timeout: 30_000 });
  await expect(errors.getByRole("alert")).toContainText("We couldn't analyse broken.csv.");
  await expect(errors).toContainText("The file has 60 problems");
  await expect(errors).toContainText("Showing the first 20 of 60 problems.");
  await expect(errors.getByTestId("csv-error-row")).toHaveCount(20);
  await expect(errors.getByTestId("csv-error-row").first()).toContainText("visit_date");
  await expect(errors).toBeFocused();
  await expect(page.locator("body")).not.toContainText(secret);
  await expect(page.locator("body")).not.toContainText("Zelda Canary");
  await expect(tid(page, "tile-dormant")).toHaveCount(0);

  // Own messages for the other file-level problems.
  for (const [name, content, message] of [
    ["empty.csv", "", "That file is empty."],
    ["notes.txt", "x", "That isn't a .csv file"],
  ] as const) {
    await page.getByTestId("csv-file-input").setInputFiles(file(name, Buffer.from(content)));
    await expect(errors).toContainText(message);
  }
  await page.getByTestId("csv-file-input").setInputFiles(file("header.csv", Buffer.from("patient_id,visit_date,line_kind,amount\n")));
  await expect(errors).toContainText("column names but no data rows");
  await page.getByTestId("csv-file-input").setInputFiles(file("members.csv", Buffer.from("patient_id,visit_date,line_kind,amount\nP1,2026-01-01,membership,5.00\n")));
  await expect(errors).toContainText("no usable visits");
  await page.getByTestId("csv-file-input").setInputFiles(file("cols.csv", Buffer.from("patient_id,nope\n")));
  await expect(errors).toContainText("Unknown columns");

  // The panel recovers: a good file after a bad one works.
  await page.getByTestId("csv-file-input").setInputFiles(file("fixed.csv", csvFile(20)));
  await expect(tid(page, "csv-banner")).toContainText("fixed.csv", { timeout: 60_000 });
});

test("a file can be dropped, and progress is shown while it is analysed", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "empty"]);
  await page.goto("/reactivation");
  await tid(page, "import-csv").click();

  await page.route("**/csv-analysis", async (route) => {
    await new Promise((r) => setTimeout(r, 1500));
    await route.continue();
  });
  const dt = await page.evaluateHandle((text) => {
    const data = new DataTransfer();
    data.items.add(new File([text], "dropped.csv", { type: "text/csv" }));
    return data;
  }, csvFile(15).toString());
  await page.getByTestId("csv-dropzone").dispatchEvent("drop", { dataTransfer: dt });

  const progress = tid(page, "csv-progress");
  await expect(progress).toBeVisible();
  await expect(progress).toContainText("dropped.csv");
  await expect(progress.getByRole("button", { name: "Cancel" })).toBeVisible();
  await expect(tid(page, "csv-banner")).toContainText("dropped.csv", { timeout: 60_000 });
});

test("a file over 10 MB passes through the web server untouched", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "empty"]);
  await page.goto("/reactivation");
  await tid(page, "import-csv").click();
  const big = csvFile(3000, 130_000); // about 14 MB
  expect(big.length).toBeGreaterThan(10 * 1024 * 1024);
  await page.getByTestId("csv-file-input").setInputFiles(file("big.csv", big));
  await expect(tid(page, "csv-banner")).toContainText("big.csv", { timeout: 90_000 });
  await expect(tid(page, "tile-change")).toContainText("3,000 patients");
  await expect(tid(page, "tile-change")).toContainText("139,000 rows");
});

test("roles that cannot import see no Import CSV button", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "empty"]);
  await page.route("**/api/v1/auth/me", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    for (const m of body.memberships) m.role = "front_desk";
    await route.fulfill({ response, json: body });
  });
  await page.goto("/reactivation");
  await expect(page.getByRole("heading", { level: 1, name: "Upload your data to find your dormant patients" })).toBeVisible();
  await expect(tid(page, "import-csv")).toHaveCount(0);
  await expect(tid(page, "welcome-no-role")).toContainText("owner or office manager");
});
