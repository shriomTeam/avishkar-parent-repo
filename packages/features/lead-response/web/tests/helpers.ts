import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect, type Locator, type Page } from "@playwright/test";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../../../..");
const script = "packages/features/lead-response/scripts/browser_seed.py";
export const URL_SETTINGS = "/lead-response/settings";
export const API_SETTINGS = "**/api/platform/features/lead_response/settings";

export type Facts = Record<string, string | number | boolean>;

// The helper only ever uses the disposable TEST_* databases and refuses anything else.
export function seed(command: string, workspace: string, extra: string[] = []): Facts {
  const out = execFileSync("uv", ["run", "python", script, command, "--tenant-name", workspace, ...extra], {
    cwd: repoRoot,
    env: process.env,
    encoding: "utf8",
  });
  return JSON.parse(out.trim().split("\n").pop()!) as Facts;
}

/** Holds a lock on the settings table, resolves when it is held. The returned process ends by itself after `seconds`. */
export function hold(workspace: string, seconds: number): Promise<ChildProcess> {
  const child = spawn("uv", ["run", "python", script, "hold", "--tenant-name", workspace, "--seconds", String(seconds)], {
    cwd: repoRoot,
    env: process.env,
  });
  return new Promise((ok, fail) => {
    let text = "";
    child.stdout.on("data", (chunk) => {
      text += chunk;
      if (text.includes('"locked"')) ok(child);
    });
    child.on("exit", (code) => fail(new Error(`hold ended early (exit ${code}): ${text}`)));
    setTimeout(() => fail(new Error("hold did not take the lock in time")), 30_000);
  });
}

export async function signIn(page: Page, workspace: string) {
  await page.goto("/login");
  await page.getByRole("link", { name: "Continue with Google" }).click();
  await expect(page).toHaveURL(/\/onboarding$/);
  await page.getByLabel("Workspace name").fill(workspace);
  await page.getByRole("button", { name: "Create workspace", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
}

type Options = { scenario?: "standard" | "saved" | null; role?: "front_desk" };

/**
 * A fresh workspace per test: signs in, and (unless `scenario` is null) switches the feature on for it. Returns a
 * getter for the workspace name. CPU_THROTTLE=4 runs the spec on a CPU four times slower, to catch timing assumptions.
 */
export function useWorkspace(options: Options = {}) {
  let workspace = "";
  test.beforeEach(async ({ page }) => {
    const rate = Number(process.env.CPU_THROTTLE ?? 1);
    if (rate > 1) await (await page.context().newCDPSession(page)).send("Emulation.setCPUThrottlingRate", { rate });
    workspace = `Leads ${randomUUID().slice(0, 8)}`;
    await signIn(page, workspace);
    if (options.scenario !== null) seed("enable", workspace, ["--scenario", options.scenario ?? "standard"]);
    if (options.role === "front_desk") seed("front-desk", workspace);
  });
  test.afterEach(() => {
    seed("cleanup", workspace);
  });
  return () => workspace;
}

// Next streams a hidden copy of the page while it loads, so look inside <main> only.
export const tid = (page: Page, id: string): Locator => page.getByRole("main").getByTestId(id);

/** Opens the settings and waits until the page has hydrated, so nothing is clicked before React is listening. */
export async function openSettings(page: Page) {
  await page.goto(URL_SETTINGS);
  await expect(tid(page, "settings-form")).toHaveAttribute("data-ready", "true", { timeout: 30_000 });
}

export async function noHorizontalScroll(page: Page) {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(over, "the page scrolls sideways").toBeLessThanOrEqual(1);
}

/** Screenshots go to SHOT_DIR when it is set (a folder outside the repository); otherwise nothing is written. */
export async function shot(page: Page, name: string) {
  const dir = process.env.SHOT_DIR;
  if (!dir) return;
  mkdirSync(dir, { recursive: true });
  await page.screenshot({ path: resolve(dir, `${name}.png`), fullPage: true });
}

/** Presses Tab until the element with this test id has focus (keyboard-only travel), at most `max` presses. */
export async function tabTo(page: Page, testId: string, max = 80) {
  for (let i = 0; i < max; i++) {
    await page.keyboard.press("Tab");
    const id = await page.evaluate(() => document.activeElement?.getAttribute("data-testid") ?? document.activeElement?.id ?? "");
    if (id === testId) return;
  }
  throw new Error(`Tab never reached ${testId}`);
}
