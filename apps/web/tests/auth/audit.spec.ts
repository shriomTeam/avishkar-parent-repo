import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";

test("audit history paginates, filters and downloads matching events", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByRole("link", { name: "Continue with Google" }).click();
  await page.getByLabel("Workspace name").fill("Audit browser clinic");
  await page
    .getByRole("button", { name: "Create workspace", exact: true })
    .click();
  await expect(page).toHaveURL(/\/$/);
  const auth = await (await page.request.get("/api/v1/auth/me")).json();
  const base = `/api/v1/workspaces/${auth.workspace.id}`;
  for (let i = 0; i < 55; i++) {
    const response = await page.request.post(`${base}/settings`, {
      headers: {
        "X-CSRF-Token": auth.csrf_token,
        Origin: "http://127.0.0.1:3100",
      },
      data: {
        name: `Audit clinic ${i}`,
        timezone: "UTC",
        clinic_type: "wellness",
        phone: null,
        address: "",
      },
    });
    expect(response.status()).toBe(200);
  }
  await page.goto("/settings");
  await page.getByRole("tab", { name: "Audit log", exact: true }).click();
  await expect(
    page.getByRole("cell", { name: "workspace updated", exact: true }),
  ).toHaveCount(50);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(
    page.getByRole("cell", { name: "workspace updated", exact: true }),
  ).toHaveCount(5);
  await expect(
    page.getByRole("button", { name: "Next", exact: true }),
  ).toBeDisabled();
  const downloadReady = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download CSV" }).click();
  const download = await downloadReady;
  expect(await download.failure()).toBeNull();
  const csv = await readFile((await download.path())!, "utf8");
  expect(
    csv.split("\n").filter((line) => line.includes("workspace.updated")),
  ).toHaveLength(55);
  await page.getByRole("combobox", { name: "Actor", exact: true }).click();
  await page
    .getByRole("option", { name: "Browser Owner", exact: true })
    .click();
  await page.getByRole("combobox", { name: "Event", exact: true }).click();
  await page
    .getByRole("option", { name: "workspace updated", exact: true })
    .click();
  const applied = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      url.pathname === `${base}/audit` &&
      url.searchParams.get("action") === "workspace.updated" &&
      !!url.searchParams.get("actor")
    );
  });
  await page
    .getByRole("button", { name: "Apply filters", exact: true })
    .click();
  expect((await applied).ok()).toBe(true);
  await expect(
    page.getByRole("cell", { name: "workspace updated", exact: true }),
  ).toHaveCount(50);
  await page.getByLabel("From date", { exact: true }).fill("2000-01-01");
  await page.getByLabel("To date", { exact: true }).fill("2000-01-02");
  await page
    .getByRole("button", { name: "Apply filters", exact: true })
    .click();
  await expect(
    page.getByText("No matching activity", { exact: true }),
  ).toBeVisible();
  const filteredDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download CSV" }).click();
  const filteredFile = await filteredDownload;
  const filteredCsv = await readFile((await filteredFile.path())!, "utf8");
  expect(
    filteredCsv
      .split("\n")
      .filter((line) => line.includes("workspace.updated")),
  ).toHaveLength(0);
  await page
    .getByRole("button", { name: "Clear filters", exact: true })
    .click();
  await expect(
    page.getByRole("cell", { name: "workspace updated", exact: true }),
  ).toHaveCount(50);
  await page.setViewportSize({ width: 390, height: 900 });
  await expect(page.getByLabel("From date", { exact: true })).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("audit-mobile.png"),
    fullPage: true,
  });
});
