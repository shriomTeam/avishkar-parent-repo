import { test, expect, type Locator, type Page } from "@playwright/test";

// Calls use a fake microphone and a scripted model (clinic_voice_receptionist.testing), so these
// are real end-to-end runs of the pages without reaching Vertex.
test.setTimeout(90_000);
const CALL = { timeout: 30_000 }; // the first call after a cold start also waits for the dev server to compile
test.use({
  permissions: ["microphone"],
  launchOptions: {
    args: [
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
    ],
  },
});

/** Picks an option in the app's own dropdown (a combobox button with a listbox). */
async function choose(scope: Page | Locator, label: string, option: string) {
  await scope.getByRole("combobox", { name: label }).click();
  await scope.getByRole("option", { name: option }).click();
}

async function createAgent(page: Page, name: string) {
  await page.goto("/voice-receptionist/agents");
  await page.getByRole("button", { name: "Create agent", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Agent name").fill(name);
  await dialog
    .getByRole("button", { name: "Create agent", exact: true })
    .click();
  // Creating adds the tool, saves the agent and opens its page, which a cold dev server compiles on first visit.
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible(
    CALL,
  );
}

/** Opens Test studio, calls the agent, lets the scripted caller give details, and hangs up. */
async function takeTestCall(page: Page, agentName: string) {
  await page.getByRole("link", { name: "Test studio", exact: true }).click();
  await page
    .getByLabel("Agent", { exact: true })
    .selectOption({ label: agentName });
  await page.getByRole("button", { name: "Start test call" }).click();
  await expect(page.getByTestId("captured-fields")).toContainText(
    "Sam Lee",
    CALL,
  );
  await page.getByRole("button", { name: "End call" }).click();
  await expect(
    page.getByRole("link", { name: "View saved call" }),
  ).toBeVisible();
}

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
      "/voice-receptionist/test",
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

test("create, edit and save an agent, take a test call, review it and route a number", async ({
  page,
}) => {
  await createAgent(page, "Pilot receptionist");
  await page
    .getByLabel("System prompt")
    .fill("Answer practice questions and collect callback details.");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("Agent saved");
  await page.getByRole("tab", { name: "What to capture" }).click();
  await page.getByRole("button", { name: "Add field" }).click();
  const added = page.getByTestId("capture-field").last();
  await added.getByLabel("Label").fill("Preferred day");
  await expect(added.getByLabel("Key")).toHaveValue("preferred_day"); // derived from the label
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("Agent saved");

  await takeTestCall(page, "Pilot receptionist");
  await expect(page.getByTestId("tool-activity")).toContainText(
    "create_lead",
    CALL,
  );
  await expect(page.getByTestId("tool-activity")).toContainText("Success");
  await expect(page.getByTestId("live-transcript")).toContainText(
    "Thanks for calling Browser Practice",
  );
  await page.getByRole("link", { name: "View saved call" }).click();
  await expect(
    page.getByRole("heading", { name: "Pilot receptionist", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Thanks Sam, I have your details."),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Captured details" }).click();
  await expect(page.getByRole("tabpanel")).toContainText("Caller name");
  await expect(page.getByRole("tabpanel")).toContainText("+14155550123");
  await page.getByRole("tab", { name: "Tool executions" }).click();
  await expect(page.getByRole("tabpanel")).toContainText("create_lead");
  await expect(page.getByRole("tabpanel")).toContainText("+14155550123");
  await page.getByRole("tab", { name: "Raw responses" }).click();
  await expect(page.locator(".raw-events")).toContainText("turn_complete");

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

  // Deleting the agent keeps its calls.
  await page.getByRole("link", { name: "Voice agents", exact: true }).click();
  await page.getByRole("link", { name: "Open agent" }).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByRole("button", { name: "Delete agent" }).click();
  await expect(page).toHaveURL(/\/voice-receptionist\/agents$/);
  await page.getByRole("link", { name: "Call history", exact: true }).click();
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await expect(page.locator("tbody tr")).toContainText("Pilot receptionist");
});

test("the agent editor checks values before saving and keeps unsaved edits from being tested", async ({
  page,
}) => {
  await createAgent(page, "Careful agent");
  await page.getByLabel("Agent name").fill("");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.locator(".form-error")).toContainText(
    "Give the agent a name.",
  );
  await page.getByLabel("Agent name").fill("Careful agent");
  await page.getByRole("tab", { name: "What to capture" }).click();
  await page.getByRole("button", { name: "Add field" }).click();
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.locator(".form-error")).toContainText(
    "Every field needs a label.",
  );
  await page
    .getByTestId("capture-field")
    .last()
    .getByLabel("Label")
    .fill("Insurance provider");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("Agent saved");
  await page.getByRole("tab", { name: "Data & privacy" }).click();
  await expect(page.getByLabel("Save the transcript")).toBeChecked();
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

test("tools: add internal and external tools, validation, a real test run, attaching to an agent, switching off and removing", async ({
  page,
}) => {
  await page.goto("/voice-receptionist/tools");
  await expect(
    page.getByRole("heading", { name: "No tools yet" }),
  ).toBeVisible();

  // Internal tools are chosen from a list; nothing else to fill in.
  await page.getByRole("button", { name: "Add tool" }).click();
  let picker = page.getByRole("dialog");
  await expect(
    picker.getByRole("combobox", { name: "Tool type" }),
  ).toContainText("Internal");
  await expect(picker.getByRole("combobox", { name: "Action" })).toContainText(
    "Create lead",
  );
  await expect(picker).toContainText("does NOT notify the team");
  await picker.getByRole("button", { name: "Add tool" }).click();
  await expect(page.getByRole("status")).toHaveText("Tool added");
  await expect(
    page.getByRole("heading", { name: "create_lead", exact: true }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Add tool" }).click();
  picker = page.getByRole("dialog");
  await expect(picker.getByRole("combobox", { name: "Action" })).toContainText(
    "Update lead",
  );
  await picker.getByRole("combobox", { name: "Action" }).click();
  await expect(
    picker.getByRole("option", { name: /Create lead/ }),
  ).toHaveAttribute("aria-disabled", "true");
  await expect(
    picker.getByRole("option", { name: /Create lead/ }),
  ).toContainText("already added");
  await page.keyboard.press("Escape"); // closes the list, not the dialog
  await expect(picker.getByRole("listbox")).toHaveCount(0);
  await expect(picker).toBeVisible();
  await picker.getByRole("button", { name: "Add tool" }).click();
  const update = page.locator("section.panel").filter({
    has: page.getByRole("heading", { name: "update_lead", exact: true }),
  });
  await expect(update).toContainText("never creates a lead");
  await update.getByRole("button", { name: "Remove" }).click();
  await page.getByRole("button", { name: "Remove tool" }).click();
  await expect(update).toHaveCount(0);

  await expect(page.getByText("Built in")).toBeVisible();
  // Internal tools have fixed arguments, so there is no schema for a clinic to look at.
  await expect(
    page.getByRole("button", { name: "View input schema" }),
  ).toHaveCount(0);
  await expect(page.locator("pre.code")).toHaveCount(0);

  // A built-in tool's wording can be changed, and put back.
  const lead = page.locator("section.panel").filter({
    has: page.getByRole("heading", { name: "create_lead", exact: true }),
  });
  await lead.getByRole("button", { name: "Edit description" }).click();
  const wording = page.getByRole("dialog");
  await expect(
    wording.getByRole("button", { name: "Reset to default" }),
  ).toBeDisabled();
  await wording
    .getByLabel("Description")
    .fill("Only create a lead for new callers.");
  await wording.getByRole("button", { name: "Save description" }).click();
  await expect(lead).toContainText("Only create a lead for new callers.");
  await expect(lead).toContainText("Custom wording");
  await lead.getByRole("button", { name: "Edit description" }).click();
  await page.getByRole("button", { name: "Reset to default" }).click();
  await page.getByRole("button", { name: "Save description" }).click();
  await expect(lead).toContainText("does NOT notify the team");
  await expect(lead).toContainText("Default wording");

  await page.getByRole("button", { name: "Add tool" }).click();
  const dialog = page.getByRole("dialog");
  await choose(dialog, "Tool type", "External: calls your own API");
  await dialog.getByLabel("Tool name").fill("lookup_hours");
  await dialog.getByLabel("Description").fill("Look up the clinic's hours");
  await dialog.getByLabel("Endpoint").fill("ftp://api.example.com/hours");
  await dialog.getByLabel("Input schema").fill("{broken");
  await dialog.getByRole("button", { name: "Save tool" }).click();
  await expect(dialog.getByRole("alert")).toContainText("valid JSON");
  await dialog
    .getByLabel("Input schema")
    .fill(
      '{"type":"object","properties":{"day":{"type":"string"}},"required":["day"]}',
    );
  await dialog.getByRole("button", { name: "Save tool" }).click();
  await expect(dialog.getByRole("alert")).toContainText("URL"); // the server explains what is wrong
  await dialog.getByLabel("Endpoint").fill("http://127.0.0.1:8001/_test/echo");
  await choose(dialog, "HTTP method", "GET");
  await dialog.getByLabel("Auth header name").fill("X-Api-Key");
  await dialog.getByLabel("Auth header value").fill("secret-123");
  await dialog.getByRole("button", { name: "Save tool" }).click();

  const panel = page.locator("section.panel").filter({
    has: page.getByRole("heading", { name: "lookup_hours", exact: true }),
  });
  await expect(panel).toBeVisible();
  await expect(panel).toContainText("X-Api-Key (saved)");
  await expect(page.getByText("secret-123")).toHaveCount(0); // the value is never shown again

  await expect(page.locator("pre.code")).toHaveCount(0); // schemas stay tucked away until asked for
  await panel.getByRole("button", { name: "View input schema" }).click();
  await expect(page.getByRole("dialog")).toContainText('"day"');
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  await panel.getByRole("button", { name: "Test tool" }).click();
  await expect(page.getByRole("dialog").getByLabel("Sample input")).toHaveValue(
    /"day": "example"/,
  );
  await page.getByRole("button", { name: "Run test" }).click();
  await expect(page.getByRole("dialog")).toContainText("Success", CALL);
  await expect(page.getByRole("dialog")).toContainText("9 to 5");
  await page.keyboard.press("Escape");

  await createAgent(page, "Tool agent");
  await page.getByRole("tab", { name: "Tools" }).click();
  await page.getByRole("checkbox", { name: /lookup_hours/ }).check();
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("Agent saved");
  await page.reload();
  await page.getByRole("tab", { name: "Tools" }).click();
  await expect(
    page.getByRole("checkbox", { name: /lookup_hours/ }),
  ).toBeChecked();
  await expect(
    page.getByRole("checkbox", { name: /create_lead/ }),
  ).toBeChecked(); // starter agents get it

  await page.getByRole("link", { name: "Tools", exact: true }).click();
  await expect(panel).toContainText("Used by 1 agent");
  await panel.getByRole("checkbox", { name: /Enable tool/ }).uncheck();
  await expect(page.getByRole("status")).toHaveText("Tool disabled");
  await expect(panel.getByRole("button", { name: "Test tool" })).toBeDisabled();

  await panel.getByRole("button", { name: "Delete" }).click();
  await page.getByRole("button", { name: "Delete tool" }).click();
  await expect(panel).toHaveCount(0);
});

test("call filters, CSV download and missing record states", async ({
  page,
}) => {
  await createAgent(page, "Filter agent");
  await takeTestCall(page, "Filter agent");
  await page.getByRole("link", { name: "Call history", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Search calls" })
    .fill("Filter agent");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await page.getByLabel("Filter call status").selectOption("Failed");
  await expect(
    page.getByRole("heading", { name: "No calls match your filters" }),
  ).toBeVisible();
  await page.getByLabel("Filter call status").selectOption("all");
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe("avishkar-calls.csv");
  await page
    .getByRole("textbox", { name: "Search calls" })
    .fill("no-such-agent");
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
  await createAgent(page, "Keyboard agent");
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
  await expect(
    page.getByRole("tab", { name: "What to capture" }),
  ).toBeFocused();
  await expect(
    page.getByRole("tab", { name: "What to capture" }),
  ).toHaveAttribute("aria-selected", "true");
});

test("session expiry hides the dashboard and returns to login", async ({
  page,
}) => {
  const firstCheck = page.waitForResponse("**/api/v1/auth/me");
  await page.goto("/voice-receptionist/settings");
  await firstCheck; // the page is hydrated and listening once its own session check has answered
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
  const firstCheck = page.waitForResponse("**/api/v1/auth/me");
  await page.goto("/voice-receptionist/settings");
  await firstCheck; // the page is hydrated and listening once its own session check has answered
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
      page.getByRole("link", { name: "Always-On Clinic", exact: true }),
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
    page.getByRole("link", { name: "Always-On Clinic", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "Voice Receptionist", exact: true })
    .click();
  await expect(page.locator(".sidebar .brand")).toBeVisible();
});
