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
  workspace = `ImportPage ${randomUUID().slice(0, 8)}`;
  await signIn(page, workspace);
});
test.afterEach(() => {
  helper("cleanup", workspace);
});

const tid = (page: Page, id: string) => page.getByRole("main").getByTestId(id);
const dataNav = (page: Page) => page.getByRole("navigation", { name: "Dormant patients data" });

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

test("Import data is in the sidebar, opens its own page, and a finished import lands on the Overview", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "empty"]);
  await page.goto("/reactivation");

  const item = dataNav(page).getByRole("link", { name: "Import data" });
  await expect(item).toBeVisible();
  await item.click();
  await expect(page).toHaveURL(/\/reactivation\/import$/);
  await expect(item).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText("Import data");
  await expect(page.getByRole("heading", { level: 1, name: "Import data" })).toBeVisible();
  await expect(tid(page, "download-template")).toBeVisible();
  await expect(tid(page, "csv-help")).toBeVisible();
  await expect(page.getByTestId("csv-choose")).toBeFocused();

  await page.getByTestId("csv-file-input").setInputFiles(csvFile(30));
  await expect(page).toHaveURL(/\/reactivation$/, { timeout: 60_000 });
  await expect(tid(page, "csv-banner")).toContainText("Showing results from march-export.csv.");
  await expect(tid(page, "tile-dormant")).toContainText("of 30 patients");
});

test("the Overview and the file results both lead to the import page", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.goto("/reactivation");
  await tid(page, "import-csv").click();
  await expect(page).toHaveURL(/\/reactivation\/import$/);
  await page.getByTestId("csv-file-input").setInputFiles(csvFile(25));
  await expect(tid(page, "csv-banner")).toContainText("march-export.csv", { timeout: 60_000 });

  await tid(page, "csv-another").click();
  await expect(page).toHaveURL(/\/reactivation\/import$/);
  await expect(page.getByTestId("csv-choose")).toBeFocused();
});

// Assign a real role in the disposable database so browser, SSR and API authorization agree.
test("front desk sees no Import data item, and the page refuses them by URL", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  helper("front-desk", workspace);
  await page.goto("/reactivation");
  await expect(tid(page, "tile-dormant")).toBeVisible();
  await expect(page.getByRole("link", { name: "Import data" })).toHaveCount(0);
  await expect(dataNav(page)).toHaveCount(0);

  await page.goto("/reactivation/import");
  await expect(tid(page, "import-refused")).toContainText("Your role can't import files. Ask the clinic owner or office manager.");
  await expect(page.getByTestId("csv-file-input")).toHaveCount(0);
  await expect(page.getByTestId("csv-choose")).toHaveCount(0);
});

test("the import page has no sideways scroll on a narrow screen", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "empty"]);
  await page.setViewportSize({ width: 768, height: 1000 });
  await page.goto("/reactivation/import");
  await expect(tid(page, "import-page")).toBeVisible();
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(over).toBeLessThanOrEqual(1);
});
