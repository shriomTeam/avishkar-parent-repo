import { test, expect } from "@playwright/test";

test("platform sign-in and onboarding are independent of voice UI", async ({
  page,
}) => {
  await page.goto("/login");
  await expect(page.locator(".auth-scope .brand img")).toHaveAttribute(
    "src",
    "/brand/avishkar-logo.png",
  );
  await expect(page.locator(".voice-scope")).toHaveCount(0);
  await expect(page.locator(".login-page")).toHaveCSS("display", "grid");
  await page.getByRole("link", { name: "Continue with Google" }).click();
  await expect(page).toHaveURL(/\/onboarding$/);
  await page.getByLabel("Workspace name").fill("Independent Platform");
  await page
    .getByRole("button", { name: "Create workspace", exact: true })
    .click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId("clinic-name")).toHaveText(
    "Independent Platform",
  );
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
});
