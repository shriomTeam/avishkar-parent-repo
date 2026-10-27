import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import { resolve, dirname } from "node:path";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test, expect, type Download, type Page } from "@playwright/test";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../../../..");
const script = "packages/features/reactivation/scripts/browser_seed.py";
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

const FOOTER = "[FOOTER TEXT PLACEHOLDER]";
const hasPdftotext = (() => {
  try {
    execFileSync("pdftotext", ["-v"], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
})();

/** Saves the download and returns the file's bytes and, from pdftotext, the text of each page. */
async function readPdf(download: Download) {
  const path = join(mkdtempSync(join(tmpdir(), "summary-")), "summary.pdf");
  await download.saveAs(path);
  const raw = execFileSync("cat", [path], { maxBuffer: 64 * 1024 * 1024 }).toString("latin1");
  const pages = hasPdftotext
    ? execFileSync("pdftotext", ["-layout", path, "-"], { encoding: "utf8" }).split("\f").filter((p) => p.trim())
    : [];
  return { raw, pages, size: raw.length };
}

function expectEveryPageBranded(pdf: { raw: string; pages: string[] }) {
  expect(pdf.raw.startsWith("%PDF-1.4")).toBe(true);
  const pageCount = Number(/\/Count (\d+)/.exec(pdf.raw)![1]);
  expect((pdf.raw.match(/\/Im1 Do/g) ?? []).length, "the logo is drawn on every page").toBe(pageCount);
  pdf.pages.forEach((text, i) => {
    expect(text, `page ${i + 1} has the brand name`).toContain("Always-On Clinic");
    expect(text, `page ${i + 1} has the footer text`).toContain(FOOTER);
    expect(text, `page ${i + 1} has its number`).toContain(`Page ${i + 1} of ${pageCount}`);
    expect(text, `page ${i + 1} says what the report holds`).toContain("Summary totals only.");
  });
  if (pdf.pages.length) expect(pdf.pages).toHaveLength(pageCount);
}

/** pdftotext reads the two headline tiles side by side: the labels, then both figures, then both hints. */
const tiles = (dormant: string, revenue: string) => `Dormant patients Recoverable revenue ${dormant} ${revenue}`;
const flat = (pages: string[]) => pages.join("\n").replace(/\s+/g, " ");

const day = (daysAgo: number) => new Date(Date.now() - daysAgo * 86_400_000).toISOString().slice(0, 10);
const HEADER = "patient_id,patient_name,email,phone,sms_consent,visit_date,line_kind,service_name,service_category,amount";
function csvFile(patients: number, o: { recent?: boolean; rows?: number } = {}) {
  const lines = [HEADER];
  for (let i = 0; i < patients; i++) {
    const last = o.recent ? 3 + (i % 10) : 200 + ((i * 17) % 500);
    for (let k = 0; k < 3; k++)
      lines.push(
        [`P${i}`, `Person ${i}`, `p${i}@example.test`, `555010${String(i).padStart(5, "0")}`, "yes", day(last + 60 * k), "service", i % 2 ? "Botox" : "Facial", i % 2 ? "Injectables" : "Facials", `${150 + (i % 900) * 7}.00`].join(","),
      );
  }
  for (let i = 0; lines.length - 1 < (o.rows ?? 0); i++)
    lines.push(`P${i % patients},Person ${i % patients},p${i % patients}@example.test,555010${String(i % patients).padStart(5, "0")},yes,${day(300)},product,SPF 50,Skincare,${20 + (i % 50)}.00`);
  return { name: "march-export.csv", mimeType: "text/csv", buffer: Buffer.from(lines.join("\n") + "\n") };
}

async function importFile(page: Page, file: ReturnType<typeof csvFile>, timeout = 60_000) {
  await page.goto("/reactivation/import");
  await expect(page.getByTestId("csv-choose")).toBeFocused(); // hydrated
  await page.getByTestId("csv-file-input").setInputFiles(file);
  await expect(tid(page, "csv-banner")).toContainText("march-export.csv", { timeout });
}

async function noHorizontalScroll(page: Page) {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(over, "the page should not scroll sideways").toBeLessThanOrEqual(1);
}

test("a saved analysis downloads a PDF that agrees with the screen, in one request, with no patient names", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.goto("/reactivation");
  await expect(tid(page, "tile-dormant")).toBeVisible();
  const screenDormant = (await tid(page, "tile-dormant").innerText()).match(/\d[\d,]*/)![0];
  const screenRevenue = (await tid(page, "tile-revenue").innerText()).match(/\$[\d,]+ to \$[\d,]+/)![0];
  const overdue = (await tid(page, "type-row-overdue_maintenance").innerText()).replace(/\s+/g, " ");
  const overdueRange = overdue.match(/\$[\d,]+ to \$[\d,]+/)![0];
  const overdueCount = overdue.match(/Overdue maintenance.*?(\d[\d,]*) (?:\$|At)/)?.[1];
  const calls: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/features/reactivation/")) calls.push(`${r.method()} ${new URL(r.url()).pathname}`);
  });

  const [download] = await Promise.all([page.waitForEvent("download"), tid(page, "summary-report").click()]);
  expect(download.suggestedFilename()).toMatch(/^dormant-patients-summary-\d{4}-\d{2}-\d{2}-saved\.pdf$/);
  const pdf = await readPdf(download);
  expectEveryPageBranded(pdf);
  if (hasPdftotext) {
    const text = flat(pdf.pages);
    expect(text).toContain(workspace);
    expect(text).toMatch(/Source: your saved analysis from [A-Z][a-z]+ \d{1,2}, \d{4}\./);
    expect(text).toContain(`${tiles(screenDormant, screenRevenue)} of `);
    expect(text).toContain(overdueRange);
    if (overdueCount) expect(text).toMatch(new RegExp(`Overdue maintenance[^$]*?${overdueCount}\\b`));
    expect(text).toContain("The standard settings:");
    expect(text).toContain("Prepaid balance: not counted as new revenue");
    expect(text).toContain("Not available"); // the group with no membership data
    for (const name of ["Zelda", "Quillfeather", "Maya", "Priya", "Risky"]) expect(text).not.toContain(name);
  }
  expect(pdf.raw).not.toMatch(/Quillfeather|@example\.test/);

  // one call fetched the totals; no patient rows were asked for
  expect(calls.filter((c) => c.includes("/summary"))).toHaveLength(1);
  expect(calls.filter((c) => c.includes("/patients") || c.includes("/report"))).toEqual([]);
  await expect(tid(page, "summary-report")).toHaveText("Download summary report");
  await expect(tid(page, "summary-error")).toHaveCount(0);
});

test("a saved analysis made with custom settings prints them", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.goto("/reactivation/settings");
  await page.getByRole("main").getByTestId("setting-dormantDays").fill("200");
  await page.getByRole("main").getByTestId("setting-topDollars").fill("5000");
  await page.getByRole("main").getByTestId("settings-save").click();
  await expect(page.getByRole("main")).toContainText("Your next analysis will use these settings.");
  // The seeded run was made before the change, so the report still prints what that run used.
  await page.goto("/reactivation");
  const [download] = await Promise.all([page.waitForEvent("download"), tid(page, "summary-report").click()]);
  const pdf = await readPdf(download);
  if (hasPdftotext) {
    const text = flat(pdf.pages);
    expect(text).toContain("The standard settings:");
    expect(text).not.toContain("anyone who has spent more than");
  }
});

test("file results download a PDF from memory: no request, a plain note that it was not saved, no file name", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "empty"]);
  await importFile(page, csvFile(25));
  const screenDormant = (await tid(page, "tile-dormant").innerText()).match(/\d[\d,]*/)![0];
  const screenRevenue = (await tid(page, "tile-revenue").innerText()).match(/\$[\d,]+ to \$[\d,]+/)![0];
  const seen: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/")) seen.push(`${r.method()} ${r.url()}`);
  });
  page.on("console", (m) => seen.push(`console ${m.type()} ${m.text()}`));

  const [download] = await Promise.all([page.waitForEvent("download"), tid(page, "summary-report").click()]);
  expect(download.suggestedFilename()).toMatch(/^dormant-patients-summary-\d{4}-\d{2}-\d{2}-from-file\.pdf$/);
  const pdf = await readPdf(download);
  expectEveryPageBranded(pdf);
  expect(pdf.raw).not.toMatch(/march-export|Person \d|@example\.test/);
  if (hasPdftotext) {
    const text = flat(pdf.pages);
    expect(text).toContain("This report is from an imported file.");
    expect(text).toContain("not saved");
    expect(text).toContain("Return rates are assumed.");
    expect(text).toContain(`${tiles(screenDormant, screenRevenue)} of 25 patients`);
    expect(text).not.toContain("march-export");
    expect(text).not.toMatch(/Person \d/);
  }
  expect(seen, "nothing was sent and nothing was logged").toEqual([]);
  await expect(page.getByTestId("mode-badge")).toHaveText("From file");
});

test("with no dormant patients there is nothing to report, and it says so", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "empty"]);
  await importFile(page, csvFile(12, { recent: true }));
  await expect(tid(page, "tile-dormant")).toContainText("0");
  await expect(tid(page, "summary-report")).toHaveAttribute("aria-disabled", "true");
  await expect(tid(page, "summary-empty")).toHaveText("No patients to report");
  let downloaded = false;
  page.on("download", () => (downloaded = true));
  await tid(page, "summary-report").click({ force: true });
  await page.waitForTimeout(500);
  expect(downloaded).toBe(false);
});

test("front desk has no summary report button", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  helper("front-desk", workspace);
  await page.goto("/reactivation");
  await expect(tid(page, "tile-dormant")).toBeVisible();
  await expect(tid(page, "summary-report")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /summary report/ })).toHaveCount(0);
});

test("the button says it is building and ignores a second press; a failure says so and can be retried", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.goto("/reactivation");
  await expect(tid(page, "tile-dormant")).toBeVisible();
  let fail = true;
  let requests = 0;
  await page.route("**/runs/*/summary", async (route) => {
    requests++;
    if (fail) return route.fulfill({ status: 500, json: { detail: "nope" } });
    await new Promise((r) => setTimeout(r, 400));
    return route.continue();
  });
  await tid(page, "summary-report").click();
  await expect(tid(page, "summary-error")).toHaveText("We couldn't build the report. Please try again.");
  await expect(tid(page, "summary-report")).toHaveText("Download summary report");

  fail = false;
  const downloads: string[] = [];
  page.on("download", (d) => downloads.push(d.suggestedFilename()));
  await tid(page, "summary-report").click();
  await expect(tid(page, "summary-report")).toHaveText("Building PDF…");
  await tid(page, "summary-report").click({ force: true }); // ignored while building
  await expect(tid(page, "summary-report")).toHaveText("Download summary report");
  await expect(tid(page, "summary-error")).toHaveCount(0);
  expect(downloads).toHaveLength(1);
  expect(requests).toBe(2); // the failed one and one good one
});

test("the three heading actions fit a 360 px screen", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.setViewportSize({ width: 360, height: 740 });
  await page.goto("/reactivation");
  await expect(tid(page, "summary-report")).toBeVisible();
  await expect(tid(page, "export-report")).toBeVisible();
  await expect(tid(page, "run-now")).toBeVisible();
  await noHorizontalScroll(page);
  const box = await tid(page, "summary-report").boundingBox();
  expect(box!.height).toBeGreaterThanOrEqual(40);
  expect(box!.x + box!.width).toBeLessThanOrEqual(360);
});

// --- scale: real Chrome numbers, printed for the report --------------------------------------------------------------------

type Measured = { ms: number; heapStartMb: number; heapPeakMb: number; rssPeakMb: number; pdfKb: number };

function rendererRssMb(): number {
  const out = execFileSync("ps", ["-eo", "rss=,args="], { encoding: "utf8" });
  const sizes = out
    .split("\n")
    .filter((l) => l.includes("--type=renderer"))
    .map((l) => Number(l.trim().split(/\s+/)[0]));
  return Math.max(0, ...sizes) / 1024;
}

async function measureDownload(page: Page, click: () => Promise<unknown>): Promise<{ download: Download; m: Measured }> {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Performance.enable");
  const heap = async () => ((await cdp.send("Performance.getMetrics")).metrics.find((x) => x.name === "JSHeapUsedSize")?.value ?? 0) / 1048576;
  const heapStart = await heap();
  let heapPeak = heapStart;
  let rssPeak = rendererRssMb();
  const timer = setInterval(() => {
    heap().then((h) => (heapPeak = Math.max(heapPeak, h))).catch(() => {});
    rssPeak = Math.max(rssPeak, rendererRssMb());
  }, 40);
  const started = Date.now();
  const [download] = await Promise.all([page.waitForEvent("download"), click()]);
  const ms = Date.now() - started;
  clearInterval(timer);
  heapPeak = Math.max(heapPeak, await heap());
  rssPeak = Math.max(rssPeak, rendererRssMb());
  return { download, m: { ms, heapStartMb: heapStart, heapPeakMb: heapPeak, rssPeakMb: rssPeak, pdfKb: 0 } };
}

const SCALES = [
  { name: "12k", patients: 12_000, rows: 116_741 },
  { name: "limits", patients: 25_000, rows: 150_000 },
] as const;

for (const scale of SCALES) {
  test(`scale ${scale.name}: a saved run of ${scale.patients} patients downloads fast and the PDF matches the screen`, async ({ page }) => {
    test.setTimeout(180_000);
    helper("seed", workspace, ["--scenario", "large", "--patients", String(scale.patients)]);
    await page.goto("/reactivation");
    await expect(tid(page, "tile-dormant")).toBeVisible();
    const screenDormant = (await tid(page, "tile-dormant").innerText()).match(/\d[\d,]*/)![0];
    const screenRevenue = (await tid(page, "tile-revenue").innerText()).match(/\$[\d,]+ to \$[\d,]+/)![0];
    const { download, m } = await measureDownload(page, () => tid(page, "summary-report").click());
    const pdf = await readPdf(download);
    m.pdfKb = Math.round(pdf.size / 1024);
    expectEveryPageBranded(pdf);
    if (hasPdftotext) {
      const text = flat(pdf.pages);
      expect(text).toContain(`${tiles(screenDormant, screenRevenue)} of `);
    }
    console.log(`PERF saved ${scale.name} ${JSON.stringify({ ...m, dormant: screenDormant })}`);
  });

  test(`scale ${scale.name}: a file of about ${scale.rows} rows downloads from memory and the PDF matches the screen`, async ({ page }) => {
    test.setTimeout(420_000);
    helper("seed", workspace, ["--scenario", "empty"]);
    await importFile(page, csvFile(scale.patients, { rows: scale.rows }), 300_000);
    const screenDormant = (await tid(page, "tile-dormant").innerText()).match(/\d[\d,]*/)![0];
    const screenRevenue = (await tid(page, "tile-revenue").innerText()).match(/\$[\d,]+ to \$[\d,]+/)![0];
    const seen: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("/api/")) seen.push(`${r.method()} ${r.url()}`);
    });
    const { download, m } = await measureDownload(page, () => tid(page, "summary-report").click());
    const pdf = await readPdf(download);
    m.pdfKb = Math.round(pdf.size / 1024);
    expectEveryPageBranded(pdf);
    if (hasPdftotext) {
      const text = flat(pdf.pages);
      expect(text).toContain(`${tiles(screenDormant, screenRevenue)} of ${scale.patients.toLocaleString("en-US")} patients`);
      expect(text).not.toMatch(/Person \d/);
    }
    expect(seen, "no request left the page").toEqual([]);
    console.log(`PERF file ${scale.name} ${JSON.stringify({ ...m, dormant: screenDormant })}`);
  });
}
