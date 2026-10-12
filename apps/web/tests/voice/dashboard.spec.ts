import { test, expect } from "@playwright/test";

async function signIn(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByRole("link", { name: "Continue with Google" }).click();
  await expect(page).toHaveURL(/\/onboarding$/);
  await page.getByLabel("Workspace name").fill("Browser Practice");
  await page
    .getByRole("button", { name: "Create workspace", exact: true })
    .click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto("/voice-receptionist");
}

test.beforeEach(async ({ page }, info) => {
  if (info.title !== "Google sign-in, protected routes and sign-out")
    await signIn(page);
});

test("Google sign-in, protected routes and sign-out", async ({ page }) => {
  await page.goto("/voice-receptionist/settings");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("textbox")).toHaveCount(0);
  // An obsolete tenant selection from the pre-auth parent must not block onboarding.
  await page.context().addCookies([
    {
      name: "clinic_tenant",
      value: "11111111-1111-1111-1111-111111111111",
      url: "http://127.0.0.1:3100",
    },
  ]);
  await signIn(page);
  for (const width of [1440, 820, 390]) {
    await page.setViewportSize({ width, height: 950 });
    for (const route of [
      "/voice-receptionist",
      "/voice-receptionist/agents",
      "/voice-receptionist/calls",
      "/voice-receptionist/settings",
    ]) {
      await page.goto(route);
      await expect(page.locator("h1").last()).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth > window.innerWidth + 1,
        ),
      ).toBeFalsy();
    }
  }
  await expect(
    page.getByText("browser@example.com", { exact: false }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Sign out", exact: true })
    .last()
    .click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/voice-receptionist");
  await expect(page).toHaveURL(/\/login$/);
});

test("create, edit and publish an agent, route a number and save a simulated call", async ({
  page,
}) => {
  await page.goto("/voice-receptionist/agents");
  await page.getByRole("button", { name: "Create agent", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Agent name").fill("Pilot receptionist");
  await dialog
    .getByRole("button", { name: "Create agent", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Pilot receptionist", exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("System prompt")
    .fill("Answer practice questions and collect callback details.");
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(
    "Draft saved for this preview session",
  );
  await page.getByRole("button", { name: "Publish", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Publish version" })
    .click();
  await expect(
    page.getByText("Live version v1", { exact: false }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Versions", exact: true }).click();
  await expect(
    page.getByRole("cell", { name: "v1", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Phone numbers", exact: true }).click();
  await page
    .getByRole("button", { name: "Connect number", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByLabel("Phone number (E.164)")
    .fill("+919876543210");
  await page
    .getByRole("dialog")
    .getByLabel("Assigned agent")
    .selectOption({ label: "Pilot receptionist" });
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Save routing" })
    .click();
  await expect(page.getByText("+919876543210", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Test studio", exact: true }).click();
  await page
    .getByLabel("Agent", { exact: true })
    .selectOption({ label: "Pilot receptionist" });
  await page.getByRole("button", { name: "Start simulated call" }).click();
  await page.getByRole("button", { name: "End simulated call" }).click();
  await page.getByRole("link", { name: "View saved call" }).click();
  await expect(
    page.getByRole("heading", { name: "Morgan Lee", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Pilot receptionist", { exact: true }).last(),
  ).toBeVisible();
});

test("variables persist and reset preserves authenticated workspace", async ({
  page,
}) => {
  await page.goto("/voice-receptionist/variables");
  await page.getByRole("button", { name: "Add variable" }).click();
  await page
    .getByRole("dialog")
    .getByLabel("Name", { exact: true })
    .fill("company_name");
  await page
    .getByRole("dialog")
    .getByLabel("Value", { exact: true })
    .fill("Duplicate");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Save variable" })
    .click();
  await expect(page.getByRole("dialog").getByRole("alert")).toHaveText(
    "A variable with this name already exists.",
  );
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Cancel" })
    .click();
  await page.getByRole("button", { name: "Edit company_name" }).click();
  await page
    .getByRole("dialog")
    .getByLabel("Value", { exact: true })
    .fill("Demo Clinic");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Save variable" })
    .click();
  await expect(page.locator("pre").last()).toContainText("Demo Clinic");
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await expect(page.getByTestId("clinic-name")).toContainText(
    "Browser Practice",
  );
  await page.getByRole("button", { name: "Reset demo", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Reset demo", exact: true })
    .click();
  await expect(page.getByTestId("clinic-name")).toContainText(
    "Browser Practice",
  );
});

test("tool validation, persistence and simulated result", async ({ page }) => {
  await page.goto("/voice-receptionist/tools");
  await page.getByRole("button", { name: "Add API tool" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Tool name").fill("lookup_hours");
  await dialog.getByLabel("Description").fill("Look up practice hours");
  await dialog.getByLabel("Endpoint").fill("/api/hours");
  await dialog.getByLabel("Input schema").fill("{broken");
  await dialog.getByRole("button", { name: "Save tool" }).click();
  await expect(dialog.getByRole("alert")).toContainText("Enter valid JSON");
  await dialog
    .getByLabel("Input schema")
    .fill('{"type":"object","properties":{}}');
  await dialog.getByRole("button", { name: "Save tool" }).click();
  await expect(
    page.getByRole("heading", { name: "lookup_hours", exact: true }),
  ).toBeVisible();
  await page
    .locator("section")
    .filter({
      has: page.getByRole("heading", { name: "lookup_hours", exact: true }),
    })
    .getByRole("button", { name: "Test tool" })
    .click();
  await expect(page.getByRole("dialog")).toContainText("No request was sent");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("link", { name: "Voice agents", exact: true }).click();
  await page.getByRole("link", { name: "Tools", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "lookup_hours", exact: true }),
  ).toBeVisible();
});

test("call filters, CSV download and missing record states", async ({
  page,
}) => {
  await page.goto("/voice-receptionist/calls");
  await page.getByRole("textbox", { name: "Search calls" }).fill("Morgan");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe("avishkar-sample-calls.csv");
  await page
    .getByRole("textbox", { name: "Search calls" })
    .fill("no-such-caller");
  await expect(
    page.getByRole("heading", { name: "No calls match your filters" }),
  ).toBeVisible();
  await page.goto("/voice-receptionist/calls/missing");
  await expect(
    page.getByRole("heading", { name: "Call not found" }),
  ).toBeVisible();
  await page.goto("/voice-receptionist/agents/missing");
  await expect(
    page.getByRole("heading", { name: "Agent not found" }),
  ).toBeVisible();
});

test("dialogs restore focus and tabs support arrow keys", async ({ page }) => {
  await page.goto("/voice-receptionist/agents");
  const create = page.getByRole("button", { name: "Create agent" });
  await create.click();
  await expect(page.getByRole("dialog").getByLabel("Agent name")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(create).toBeFocused();
  await page.getByRole("link", { name: "Open agent" }).first().click();
  const configuration = page.getByRole("tab", { name: "Configuration" });
  await configuration.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Variables" })).toBeFocused();
  await expect(page.getByRole("tab", { name: "Variables" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
});

test("session expiry hides the dashboard and returns to login", async ({
  page,
}) => {
  await page.goto("/voice-receptionist/settings");
  await expect(
    page.getByRole("button", { name: "Sign out", exact: true }).last(),
  ).toBeVisible();
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: '{"detail":"not_authenticated"}',
    }),
  );
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page).toHaveURL(/\/login$/);
});

test("session service failure hides content and supports retry", async ({
  page,
}) => {
  await page.goto("/voice-receptionist/settings");
  await expect(
    page.getByRole("button", { name: "Sign out", exact: true }).last(),
  ).toBeVisible();
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: '{"detail":"service_unavailable"}',
    }),
  );
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(
    page.getByRole("heading", { name: "Unable to check your session" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Sign out", exact: true }),
  ).toHaveCount(0);
  await page.unroute("**/api/v1/auth/me");
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Sign out", exact: true }).last(),
  ).toBeVisible();
});

test("original voice shell and platform return work across screen sizes", async ({
  page,
}) => {
  for (const width of [1440, 820, 390]) {
    await page.setViewportSize({ width, height: 950 });
    await page.goto("/voice-receptionist");
    await expect(page.locator(".sidebar .brand")).toBeVisible();
    await expect(
      page.getByRole("navigation", { name: "Workspace navigation" }),
    ).toBeVisible();
    await expect(page.locator(".shell header .breadcrumb")).toContainText(
      "Overview",
    );
    await expect(
      page.getByText("Always-On Clinic", { exact: true }),
    ).toHaveCount(0);
    await expect(page.locator(".voice-navigation")).toHaveCount(0);
    if (width > 700) {
      await expect(page.getByTestId("clinic-name")).toHaveText(
        "Browser Practice",
      );
      const sidebar = await page.locator(".sidebar").boundingBox();
      const main = await page.locator(".shell main").boundingBox();
      expect(main!.x).toBeGreaterThanOrEqual(sidebar!.x + sidebar!.width);
      expect(
        await page
          .locator(".voice-scope")
          .evaluate((el) => getComputedStyle(el).zoom),
      ).toBe("0.9");
    }
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth + 1,
      ),
    ).toBeFalsy();
    await page.screenshot({
      path: test.info().outputPath(`voice-restored-${width}.png`),
      fullPage: true,
    });
  }
  await page.getByRole("link", { name: "All clinic products" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(
    page.getByText("Always-On Clinic", { exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Voice Receptionist", exact: true }).click();
  await expect(page.locator(".sidebar .brand")).toBeVisible();
});
