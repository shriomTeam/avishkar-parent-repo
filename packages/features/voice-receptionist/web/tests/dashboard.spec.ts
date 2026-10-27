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
  await choose(page, "Agent", agentName);
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
  await expect(page.getByTestId("raw-events")).toContainText("turn_complete");

  // Phone numbers: search, buy (against a fake Twilio), assign, and release.
  await page.getByRole("link", { name: "Phone numbers", exact: true }).click();
  await expect(page.getByText("No phone numbers yet")).toBeVisible();
  await page.getByRole("button", { name: "Buy a number", exact: true }).click();
  const buy = page.getByRole("dialog");
  await buy.getByLabel("Area code (optional)").fill("415");
  await buy.getByRole("button", { name: "Search numbers" }).click();
  await buy.getByRole("radio").first().check();
  await expect(buy).toContainText("charges your Twilio account");
  await choose(buy, "Assigned agent", "Pilot receptionist");
  await buy.getByRole("button", { name: "Buy number" }).click();
  const owned = page.getByRole("row").filter({ hasText: "+1 (415) 555-" });
  await expect(owned).toContainText("Pilot receptionist");
  await expect(owned).toContainText("Connected");

  await owned.getByRole("button", { name: /^Manage/ }).click();
  const manage = page.getByRole("dialog");
  await choose(manage, "Assigned agent", "Unassigned");
  await manage.getByRole("button", { name: "Save routing" }).click();
  await expect(owned).toContainText("Unassigned");

  await owned.getByRole("button", { name: /^Manage/ }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Release number" })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Release number" })
    .click();
  await expect(owned).toHaveCount(0);

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
  await expect(
    page.getByRole("alert").filter({ hasText: "Give the agent a name." }),
  ).toBeVisible();
  await page.getByLabel("Agent name").fill("Careful agent");
  await page.getByRole("tab", { name: "What to capture" }).click();
  await page.getByRole("button", { name: "Add field" }).click();
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Every field needs a label." }),
  ).toBeVisible();
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

test("a recording agent keeps the call audio, which plays back in call history beside the transcript", async ({
  page,
}) => {
  await createAgent(page, "Recorded line");
  await page.getByRole("tab", { name: "Data & privacy" }).click();
  const record = page.getByLabel("Record the call");
  await expect(record).not.toBeChecked(); // off unless chosen
  await record.check();
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("Agent saved");

  await takeTestCall(page, "Recorded line");
  await page.getByRole("link", { name: "View saved call" }).click();
  await expect(
    page.getByText("Thanks Sam, I have your details."),
  ).toBeVisible();
  await expect(page.locator("audio")).toHaveCount(0); // nothing is downloaded until someone presses Play
  await page.getByRole("button", { name: "Play recording" }).click();
  const audio = page.locator("audio");
  await expect(audio).toHaveCount(1, CALL);
  await expect(
    page.getByRole("button", { name: "Pause recording" }),
  ).toBeVisible(CALL); // it started playing
  await expect(page.getByLabel("Seek")).toBeEnabled();
  await expect(page.locator("a[download], [download]")).toHaveCount(0); // no way to download it from the page
  await page.getByRole("button", { name: /Playback speed 1×/ }).click();
  await expect(
    page.getByRole("button", { name: /Playback speed 1.25×/ }),
  ).toBeVisible();
  expect(await audio.evaluate((el: HTMLAudioElement) => el.playbackRate)).toBe(
    1.25,
  );
  expect(await audio.evaluate((el: HTMLAudioElement) => el.controls)).toBe(
    false,
  );
  const bytes = await audio.evaluate(async (el: HTMLAudioElement) => {
    const blob = await (await fetch(el.src)).blob();
    return new Uint8Array(await blob.arrayBuffer()).slice(0, 4);
  });
  expect(String.fromCharCode(...bytes)).toBe("RIFF");
});

test("an agent that does not record leaves no player in call history", async ({
  page,
}) => {
  await createAgent(page, "Unrecorded line");
  await takeTestCall(page, "Unrecorded line");
  await page.getByRole("link", { name: "View saved call" }).click();
  await expect(
    page.getByText("Thanks Sam, I have your details."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Play recording" }),
  ).toHaveCount(0);
});

test("selects are the app's own dropdown: styled list, keyboard and form use", async ({
  page,
}) => {
  await createAgent(page, "First agent");
  await createAgent(page, "Second agent");
  await page.getByRole("link", { name: "Test studio", exact: true }).click();
  const agent = page.getByRole("combobox", { name: "Agent" });
  await expect(page.locator("select")).toHaveCount(0); // no browser-native menus on this screen
  await agent.click();
  await expect(page.getByRole("listbox")).toBeVisible();
  await expect(page.getByRole("option")).toHaveCount(2);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("listbox")).toHaveCount(0);
  await agent.focus();
  await page.keyboard.press("ArrowDown"); // opens
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("listbox")).toHaveCount(0);
  const chosen = await agent.innerText();
  expect(["First agent", "Second agent"]).toContain(chosen.trim());
  // Inside a form (Create agent): the choice is submitted through the hidden input.
  await page.goto("/voice-receptionist/agents");
  await page.getByRole("button", { name: "Create agent", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Agent name").fill("From a dropdown");
  await choose(dialog, "Purpose", "Enquiry assistant");
  await dialog
    .getByRole("button", { name: "Create agent", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "From a dropdown", exact: true }),
  ).toBeVisible(CALL);
});

test("variables: add, edit, use in a prompt, refuse unknown names, block deleting one in use", async ({
  page,
}) => {
  await page.goto("/voice-receptionist/variables");
  await expect(
    page.getByRole("heading", { name: "No variables yet" }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "{{clinic_name}}" }),
  ).toBeVisible(); // built in, listed for reference

  await page.getByRole("button", { name: "Add variable" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name", { exact: true }).fill("clinic_name");
  await dialog.getByLabel("Value", { exact: true }).fill("Duplicate");
  await dialog.getByRole("button", { name: "Save variable" }).click();
  await expect(dialog.getByRole("alert")).toContainText("built in");
  await dialog.getByLabel("Name", { exact: true }).fill("hours");
  await dialog
    .getByLabel("Value", { exact: true })
    .fill("Monday to Friday, 9 to 5");
  await dialog.getByRole("button", { name: "Save variable" }).click();
  const row = page.getByRole("row", { name: /\{\{hours\}\}/ });
  await expect(row).toContainText("Monday to Friday, 9 to 5");
  await expect(row).toContainText("No agent");

  await page.getByRole("button", { name: "Edit hours" }).click();
  await expect(page.getByRole("dialog")).toContainText("cannot be changed");
  await page
    .getByRole("dialog")
    .getByLabel("Value", { exact: true })
    .fill("Daily, 8 to 6");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Save variable" })
    .click();
  await expect(row).toContainText("Daily, 8 to 6");

  await createAgent(page, "Hours agent");
  await expect(page.getByTestId("variable-hint")).toContainText("{{hours}}");
  await page.getByLabel("System prompt").fill("We are open {{hourz}}.");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Unknown variables: {{hourz}}" }),
  ).toBeVisible();
  await page
    .getByLabel("System prompt")
    .fill("We are open {{hours}} at {{clinic_name}}.");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("Agent saved");

  await page.getByRole("link", { name: "Variables", exact: true }).click();
  await expect(row).toContainText("Hours agent");
  await page.getByRole("button", { name: "Delete hours" }).click();
  await page.getByRole("button", { name: "Delete variable" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Used by Hours agent" }),
  ).toBeVisible();
  await expect(row).toBeVisible();

  await page.getByRole("link", { name: "Voice agents", exact: true }).click();
  await page.getByRole("link", { name: "Open agent" }).click();
  await page.getByLabel("System prompt").fill("No variables here.");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("Agent saved");
  await page.getByRole("link", { name: "Variables", exact: true }).click();
  await page.getByRole("button", { name: "Delete hours" }).click();
  await page.getByRole("button", { name: "Delete variable" }).click();
  await expect(row).toHaveCount(0);
});

test("knowledge base: upload, see it become ready, replace, and delete", async ({
  page,
}) => {
  const name = `hours-${Date.now()}.txt`;
  const text = (words: string) => Buffer.from(`Opening hours\n\n${words}`);
  await page.goto("/voice-receptionist");
  await page.getByRole("link", { name: "Knowledge base", exact: true }).click();
  await page.getByLabel("Choose a file").setInputFiles({
    name,
    mimeType: "text/plain",
    buffer: text(`We are open nine to five. ${name}`),
  });
  const row = page.getByRole("row").filter({ hasText: name });
  await expect(row).toContainText("Ready", CALL);

  // Test search shows what an agent would find, and says so when nothing fits.
  await page.getByLabel("Question").fill("we are open nine to five");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByTestId("search-result").first()).toContainText(
    name,
    CALL,
  );
  await page.getByLabel("Question").fill("quantum chromodynamics lattice");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByText("Nothing in your documents")).toBeVisible();

  // The same file again is refused in plain words.
  await page.getByLabel("Choose a file").setInputFiles({
    name: `copy-${name}`,
    mimeType: "text/plain",
    buffer: text(`We are open nine to five. ${name}`),
  });
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "already in your knowledge base" }),
  ).toBeVisible();

  // A different file with the same name asks what to do.
  await page.getByLabel("Choose a file").setInputFiles({
    name,
    mimeType: "text/plain",
    buffer: text(`Now open until six. ${name}`),
  });
  await page.getByRole("button", { name: "Replace", exact: true }).click();
  // The old file is removed once the new one is ready; reload so the list is the server's, not a stale view.
  await expect(async () => {
    await page.reload();
    await expect(row).toHaveCount(1, { timeout: 2_000 });
    await expect(row).toContainText("Ready", { timeout: 2_000 });
  }).toPass(CALL);

  await page.getByRole("button", { name: `Delete ${name}` }).click();
  await page.getByRole("button", { name: "Delete document" }).click();
  await expect(row).toHaveCount(0);
});

test("reset demo keeps the signed-in workspace", async ({ page }) => {
  await page.goto("/voice-receptionist/settings");
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
  const update = page.getByTestId("tool-card").filter({
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
  await expect(page.locator("pre")).toHaveCount(0);

  // A built-in tool's wording can be changed, and put back.
  const lead = page.getByTestId("tool-card").filter({
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

  const panel = page.getByTestId("tool-card").filter({
    has: page.getByRole("heading", { name: "lookup_hours", exact: true }),
  });
  await expect(panel).toBeVisible();
  await expect(panel).toContainText("X-Api-Key (saved)");
  await expect(page.getByText("secret-123")).toHaveCount(0); // the value is never shown again

  await expect(page.locator("pre")).toHaveCount(0); // schemas stay tucked away until asked for
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
  await choose(page, "Filter call status", "Failed");
  await expect(
    page.getByRole("heading", { name: "No calls match your filters" }),
  ).toBeVisible();
  await choose(page, "Filter call status", "All statuses");
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
    await expect(page.getByTestId("voice-sidebar")).toBeVisible();
    await expect(
      page.getByRole("navigation", { name: "Workspace navigation" }),
    ).toBeVisible();
    await expect(page.getByTestId("voice-breadcrumb")).toContainText(
      "Overview",
    );
    await expect(
      page.getByRole("link", { name: "Always-On Clinic", exact: true }),
    ).toHaveCount(0);
    if (width > 700) {
      await expect(page.getByTestId("clinic-name")).toHaveText(
        "Browser Practice",
      );
      const sidebar = await page.getByTestId("voice-sidebar").boundingBox();
      const main = await page.getByTestId("voice-main").boundingBox();
      expect(main!.x).toBeGreaterThanOrEqual(sidebar!.x + sidebar!.width);
      expect(
        await page
          .getByTestId("voice-app")
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
  await expect(page.getByTestId("voice-sidebar")).toBeVisible();
});
