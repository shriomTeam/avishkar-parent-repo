import { test, expect } from "@playwright/test";

test("platform sign-in and onboarding are independent of voice UI", async ({
  page,
}, testInfo) => {
  await page.goto("/login");
  await expect(page.locator(".auth-scope .brand img")).toHaveAttribute(
    "src",
    "/brand/avishkar-logo.png",
  );
  await expect(page.getByTestId("voice-app")).toHaveCount(0);
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
  await expect(
    page.getByRole("heading", { name: "Your active products" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Sign out", exact: true }),
  ).toHaveCount(0);
  for (const width of [1440, 820, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect(
      page.getByRole("heading", { name: "Your active products" }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  }
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page
    .getByRole("heading", { name: "Your active products" })
    .scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: testInfo.outputPath("homepage-desktop.png"),
    fullPage: false,
  });
  await page
    .getByRole("button", { name: "Account menu for Browser Owner" })
    .click();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "Account menu for Browser Owner" }),
  ).toBeFocused();
  await page
    .getByRole("button", { name: "Account menu for Browser Owner" })
    .click();
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(
    page.getByRole("heading", { name: "Workspace information", exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Workspace name", { exact: true })
    .fill("Updated Workspace");
  await page.getByLabel("Clinic address").fill("Bengaluru, Karnataka");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.getByTestId("clinic-name")).toHaveText("Updated Workspace");
  await page.reload();
  await expect(page.getByLabel("Workspace name", { exact: true })).toHaveValue(
    "Updated Workspace",
  );
  await expect(page.getByLabel("Clinic address")).toHaveValue(
    "Bengaluru, Karnataka",
  );
  await page.getByLabel("Workspace name", { exact: true }).fill("Unsaved");
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByLabel("Workspace name", { exact: true })).toHaveValue(
    "Updated Workspace",
  );
  await page.screenshot({
    path: testInfo.outputPath("settings-workspace.png"),
    fullPage: false,
  });
  await page.getByRole("tab", { name: "User management", exact: true }).click();
  await expect(page.getByRole("cell", { name: /Browser Owner/ })).toBeVisible();
  await page
    .getByRole("textbox", { name: "Search members" })
    .fill("missing@example.com");
  await expect(
    page.getByRole("heading", { name: "No members found" }),
  ).toBeVisible();
  await page.getByRole("textbox", { name: "Search members" }).fill("");
  await page.getByRole("button", { name: "Invite user", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Invite user" })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Send invitation" }),
  ).toBeEnabled();
  await page.screenshot({
    path: testInfo.outputPath("settings-invite.png"),
    fullPage: false,
  });
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "Invite user", exact: true }),
  ).toBeFocused();
  await page.getByRole("tab", { name: "Audit log", exact: true }).click();
  await expect(
    page.getByRole("cell", { name: "workspace updated", exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 900 });
  await page.getByRole("tab", { name: "Workspace", exact: true }).click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("settings-mobile.png"),
    fullPage: false,
  });
  await page
    .getByRole("button", { name: "Account menu for Browser Owner" })
    .click();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
});

test("workspace creation stays disabled before scripts hydrate", async ({
  browser,
}) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  try {
    const response = await context.request.get(
      "http://127.0.0.1:3100/api/v1/auth/google/login",
    );
    expect(response.ok()).toBe(true);
    const page = await context.newPage();
    await page.goto("/onboarding");
    await expect(
      page.getByRole("button", { name: "Create workspace", exact: true }),
    ).toBeDisabled();
    await page.getByLabel("Workspace name").fill("Should not be submitted");
    await expect(page).toHaveURL(/\/onboarding$/);
  } finally {
    await context.close();
  }
});
