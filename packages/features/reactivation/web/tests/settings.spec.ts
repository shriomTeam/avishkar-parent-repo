import { execFile, execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import { resolve, dirname } from "node:path";
import { test, expect, type Page } from "@playwright/test";

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
  // CPU_THROTTLE=4 runs the spec on a CPU four times slower, to catch timing assumptions.
  const rate = Number(process.env.CPU_THROTTLE ?? 1);
  if (rate > 1) await (await page.context().newCDPSession(page)).send("Emulation.setCPUThrottlingRate", { rate });
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


const box = (page: Page, key: string) => page.getByRole("main").getByTestId(`setting-${key}`);

test("the settings page edits, validates, saves and resets", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.goto("/reactivation/settings");

  // Defaults, in plain words, with an example that follows the number.
  await expect(tid(page, "settings-status")).toContainText("Using the standard settings.");
  await expect(box(page, "dormantDays")).toHaveValue("180");
  await expect(box(page, "topPercent")).toHaveValue("20");
  await expect(box(page, "topDollars")).toHaveValue("");
  await expect(page.getByRole("main")).toContainText("Leave this empty to use the percentage above on its own.");
  await expect(page.getByRole("main")).toContainText("whichever is shorter");
  await expect(tid(page, "settings-reset")).toBeDisabled();
  await expect(tid(page, "settings-save")).toBeDisabled();

  // An edit makes an unsaved state; a bad value blocks Save and says why.
  await box(page, "dormantDays").fill("200");
  await expect(page.getByRole("main")).toContainText("A patient who last visited more than 200 days ago counts as dormant.");
  await expect(tid(page, "settings-savebar")).toContainText("You have unsaved changes.");
  await expect(tid(page, "settings-save")).toBeEnabled();
  await box(page, "topPercent").fill("80");
  await expect(tid(page, "setting-topPercent-error")).toHaveText("Enter a number from 1 to 50.");
  await expect(tid(page, "settings-save")).toBeDisabled();
  await box(page, "topPercent").fill("10");
  await box(page, "topDollars").fill("5,000");
  await expect(tid(page, "setting-topDollars-error")).toContainText("whole number");
  await box(page, "topDollars").fill("5000");
  await expect(page.getByRole("main")).toContainText("more than $5,000 in total counts as a top spender");
  await box(page, "rateLow").fill("30");
  await expect(tid(page, "setting-rateHigh-error")).toHaveText("The highest share can't be lower than the lowest.");
  await box(page, "rateLow").fill("5");

  // Discard puts everything back.
  await tid(page, "settings-discard").click();
  await expect(box(page, "dormantDays")).toHaveValue("180");
  await expect(tid(page, "settings-savebar")).toContainText("No unsaved changes.");

  // Save for real.
  await box(page, "dormantDays").fill("200");
  await box(page, "topDollars").fill("5000");
  await page.getByRole("main").getByTestId("setting-switch-unused_balance").uncheck();
  await tid(page, "settings-save").click();
  await expect(page.getByRole("main")).toContainText("Your next analysis will use these settings.");
  await expect(tid(page, "settings-status")).toContainText("Using your saved settings (version 1).");

  // It is really saved, and the Overview says its figures are older than the settings.
  await page.reload();
  await expect(box(page, "dormantDays")).toHaveValue("200");
  await expect(box(page, "topDollars")).toHaveValue("5000");
  await expect(page.getByRole("main").getByTestId("setting-switch-unused_balance")).not.toBeChecked();
  await page.goto("/reactivation");
  await expect(page.getByRole("main")).toContainText("Your settings changed after this analysis.");

  // Reset is a form action until saved, then a new version.
  await page.goto("/reactivation/settings");
  await tid(page, "settings-reset").click();
  await expect(box(page, "dormantDays")).toHaveValue("180");
  await expect(box(page, "topDollars")).toHaveValue("");
  await expect(tid(page, "settings-savebar")).toContainText("You have unsaved changes.");
  await tid(page, "settings-save").click();
  await expect(tid(page, "settings-status")).toContainText("version 2");
  await expect(tid(page, "settings-reset")).toBeDisabled();
});

test("the import page says which settings the file will use", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.goto("/reactivation/import");
  await expect(tid(page, "import-settings")).toContainText("analysed with the standard settings");
  await expect(tid(page, "import-settings").getByRole("link", { name: "Change settings" })).toHaveAttribute(
    "href",
    "/reactivation/settings",
  );
});

test("the settings page fits a 360 px screen", async ({ page }) => {
  helper("seed", workspace, ["--scenario", "full"]);
  await page.setViewportSize({ width: 360, height: 740 });
  await page.goto("/reactivation/settings");
  await expect(box(page, "dormantDays")).toBeVisible();
  await box(page, "dormantDays").fill("200");
  await expect(tid(page, "settings-save")).toBeVisible();
  await noHorizontalScroll(page);
});
