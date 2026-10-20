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
  workspace = `Menu ${randomUUID().slice(0, 8)}`;
  await signIn(page, workspace);
  helper("seed", workspace, ["--scenario", "full"]);
});
test.afterEach(() => {
  helper("cleanup", workspace);
});

const menuButton = (page: Page) => page.getByRole("button", { name: "Menu", exact: true });
const sections = (page: Page) => page.getByRole("navigation", { name: "Dormant patients sections" });
const dataNav = (page: Page) => page.getByRole("navigation", { name: "Dormant patients data" });
const main = (page: Page) => page.getByRole("main");
const panelOf = async (page: Page) => page.locator(`[id="${await menuButton(page).getAttribute("aria-controls")}"]`);

async function overflow(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
}

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

for (const width of [768, 360]) {
  test(`at ${width} px the sidebar is a menu: it opens, closes, and Escape and a chosen link behave`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/reactivation");

    // closed: only the top bar, the badge and the footer show, and they stay correct
    const button = menuButton(page);
    await expect(button).toBeVisible();
    await expect(button).toHaveAttribute("aria-expanded", "false");
    const panel = await panelOf(page);
    await expect(panel).toBeHidden();
    await expect(sections(page)).toBeHidden();
    await expect(page.getByTestId("mode-badge")).toBeVisible();
    await expect(page.getByTestId("mode-badge")).toHaveText("Saved data");
    await expect(page.getByTestId("shell-footer")).toBeVisible();
    await expect(page.getByTestId("shell-footer")).toContainText("Showing your last saved analysis");
    const box = await button.boundingBox();
    expect(box!.width, "44 px hit area").toBeGreaterThanOrEqual(44);
    expect(box!.height, "44 px hit area").toBeGreaterThanOrEqual(44);

    // open: the same content as the sidebar, and focus on the first navigation link
    await button.click();
    await expect(button).toHaveAttribute("aria-expanded", "true");
    await expect(panel).toBeVisible();
    await expect(sections(page).getByRole("link", { name: "Overview" })).toBeFocused();
    await expect(sections(page).getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    await expect(sections(page).getByRole("link")).toHaveText(["Overview", "Runs", "Settings"]);
    await expect(dataNav(page).getByRole("link")).toHaveText(["Import data", "Imported file"]);
    await expect(page.getByRole("link", { name: "← All clinic products" })).toBeVisible();
    await expect(page.getByTestId("clinic-name")).toBeVisible();
    await expect(page.getByTestId("status-card")).toContainText("Saved analysis");
    await expect(page.getByTestId("profile-name")).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
    await expect(page.getByRole("complementary")).toHaveCount(1);
    await expect(main(page)).toHaveCount(1);
    expect(await overflow(page), "no sideways scroll with the menu open").toBeLessThanOrEqual(1);
    await expect(page.getByTestId("mode-badge")).toBeVisible();

    // the button closes it again
    await button.click();
    await expect(button).toHaveAttribute("aria-expanded", "false");
    await expect(panel).toBeHidden();

    // Escape closes it and puts focus back on the button
    await button.click();
    await expect(sections(page).getByRole("link", { name: "Overview" })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(button).toHaveAttribute("aria-expanded", "false");
    await expect(button).toBeFocused();

    // choosing a link closes it, goes to the page, and leaves focus on the page's content
    await button.click();
    await sections(page).getByRole("link", { name: "Runs" }).click();
    await expect(page).toHaveURL(/\/reactivation\/runs$/);
    await expect(button).toHaveAttribute("aria-expanded", "false");
    await expect(panel).toBeHidden();
    await expect(main(page)).toBeFocused();
    await expect(page.getByRole("heading", { level: 1, name: "Runs" })).toBeVisible();
    await expect(page.getByTestId("mode-badge")).toBeVisible();
  });

  test(`at ${width} px the skip link works and no page scrolls sideways`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/reactivation");
    await expect(main(page).getByTestId("tile-dormant")).toBeVisible();
    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Skip to content" });
    await expect(skip).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(main(page)).toBeFocused();

    for (const path of ["/reactivation", "/reactivation/types/overdue_maintenance", "/reactivation/runs", "/reactivation/settings", "/reactivation/import", "/reactivation/file"]) {
      await page.goto(path);
      await expect(main(page)).toBeVisible();
      await expect(page.getByTestId("mode-badge")).toBeVisible();
      expect(await overflow(page), `${path} closed`).toBeLessThanOrEqual(1);
      await menuButton(page).click();
      expect(await overflow(page), `${path} with the menu open`).toBeLessThanOrEqual(1);
    }
  });
}

test("at 360 px an imported file and its table fit the screen", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 900 });
  await page.goto("/reactivation/import");
  await expect(page.getByTestId("csv-choose")).toBeFocused(); // hydrated
  await page.getByTestId("csv-file-input").setInputFiles(csvFile(25));
  await expect(main(page).getByTestId("csv-banner")).toContainText("march-export.csv", { timeout: 60_000 });
  expect(await overflow(page), "file results").toBeLessThanOrEqual(1);
  await expect(page.getByTestId("mode-badge")).toHaveText("From file");
  await menuButton(page).click();
  await expect(page.getByTestId("status-card")).toContainText("Not saved");
  await dataNav(page).getByRole("link", { name: "Imported file" }).click();
  await expect(main(page).getByTestId("file-table")).toBeVisible();
  expect(await overflow(page), "the file table scrolls inside its region").toBeLessThanOrEqual(1);
});

test("the menu can be used from the keyboard alone", async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 900 });
  await page.goto("/reactivation");
  await expect(main(page).getByTestId("tile-dormant")).toBeVisible();

  // Tab reaches the Menu button after the skip link and the brand
  const reached: string[] = [];
  for (let i = 0; i < 6 && !(await menuButton(page).evaluate((b) => b === document.activeElement)); i++) {
    await page.keyboard.press("Tab");
    reached.push(await page.evaluate(() => (document.activeElement?.textContent ?? "").trim().slice(0, 30)));
  }
  await expect(menuButton(page)).toBeFocused();
  expect(reached[0]).toBe("Skip to content");

  await page.keyboard.press("Enter");
  await expect(menuButton(page)).toHaveAttribute("aria-expanded", "true");
  await expect(sections(page).getByRole("link", { name: "Overview" })).toBeFocused();

  // Tab walks the panel in reading order, ending on Sign out
  const order: string[] = [];
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press("Tab");
    const name = await page.evaluate(() => (document.activeElement?.textContent ?? "").trim());
    order.push(name);
    if (name === "Sign out") break;
  }
  expect(order).toContain("Runs");
  expect(order).toContain("Settings");
  expect(order).toContain("Import data");
  expect(order).toContain("Imported file");
  expect(order.at(-1)).toBe("Sign out");

  // Escape leaves the panel and lands on the button; Enter opens again; Settings is chosen with Enter
  await page.keyboard.press("Escape");
  await expect(menuButton(page)).toBeFocused();
  await expect(menuButton(page)).toHaveAttribute("aria-expanded", "false");
  await page.keyboard.press("Enter");
  await sections(page).getByRole("link", { name: "Settings" }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/reactivation\/settings$/);
  await expect(menuButton(page)).toHaveAttribute("aria-expanded", "false");
  await expect(main(page)).toBeFocused();
});

test("on a wide screen the sidebar is fixed and there is no Menu button; reduced motion adds no animation", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/reactivation");
  await expect(sections(page)).toBeVisible();
  await expect(menuButton(page)).toBeHidden();
  await expect(page.getByTestId("status-card")).toBeVisible();

  await page.setViewportSize({ width: 768, height: 900 });
  await menuButton(page).click();
  const motion = await page.evaluate(() => {
    const els = [document.querySelector(".dp-panel"), document.querySelector(".dp-menu-btn")] as HTMLElement[];
    return els.map((e) => {
      const s = getComputedStyle(e);
      return `${s.transitionDuration}|${s.animationName}`;
    });
  });
  for (const m of motion) expect(m).toMatch(/^0s\|none$/);
});
