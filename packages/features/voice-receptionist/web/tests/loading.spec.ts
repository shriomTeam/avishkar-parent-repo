import { test, expect, type Page } from "@playwright/test";

// While a screen's data is on its way it shows a skeleton shaped like the screen, and the real page replaces it.
// The API is held back (not slowed by a timer) until the test releases it, so the skeleton is there for as long
// as the test needs to look at it.
test.setTimeout(90_000);
const FIRST_COMPILE = { timeout: 30_000 }; // a cold dev server compiles each screen the first time it is opened

async function signIn(page: Page) {
  await page.goto("/login");
  await page.getByRole("link", { name: "Continue with Google" }).click();
  await expect(page).toHaveURL(/\/onboarding$/);
  await page.getByLabel("Workspace name").fill("Browser Practice");
  await page
    .getByRole("button", { name: "Create workspace", exact: true })
    .click();
  await expect(page).toHaveURL(/\/$/);
}

/**
 * Holds back every call to the voice API until `release()` is called. Handlers are left in place (a handler whose gate
 * is open lets requests straight through), because removing one while a request is waiting makes that request fail.
 */
async function holdApi(page: Page) {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/api/platform/**", async (route) => {
    await gate;
    await route.continue();
  });
  return async () => release();
}

const SCREENS = [
  ["/voice-receptionist", "overview", "Your practice, in conversation."],
  ["/voice-receptionist/agents", "agents", "Voice agents"],
  ["/voice-receptionist/calls", "calls", "Call history"],
  ["/voice-receptionist/test", "test-studio", "Test studio"],
  ["/voice-receptionist/tools", "tools", "Tools"],
  ["/voice-receptionist/variables", "variables", "Variables"],
  ["/voice-receptionist/knowledge", "knowledge", "Knowledge base"],
  ["/voice-receptionist/numbers", "numbers", "Phone numbers"],
] as const;

test("each screen shows a skeleton of itself while its data loads, then the real page", async ({
  page,
}) => {
  await signIn(page);
  for (const [path, id, heading] of SCREENS) {
    const release = await holdApi(page);
    await page.goto(path);
    await expect(page.getByTestId(`loading-${id}`)).toBeVisible(FIRST_COMPILE);
    // Nothing of the real page is on screen yet, and the skeleton is announced once as loading.
    await expect(
      page.getByRole("heading", { name: heading, exact: true }),
    ).toHaveCount(0);
    await expect(page.getByTestId(`loading-${id}`)).toHaveAttribute(
      "aria-busy",
      "true",
    );
    await release();
    await expect(
      page.getByRole("heading", { name: heading, exact: true }),
    ).toBeVisible(FIRST_COMPILE);
    await expect(page.getByTestId(`loading-${id}`)).toHaveCount(0);
  }
});

test("the agent editor shows its own skeleton, and a failed load shows an error with Retry instead", async ({
  page,
}) => {
  await signIn(page);
  await page.goto("/voice-receptionist/agents");
  await page.getByRole("button", { name: "Create agent", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Agent name").fill("Skeleton agent");
  await dialog
    .getByRole("button", { name: "Create agent", exact: true })
    .click();
  // Creating an agent opens its editor.
  await expect(page).toHaveURL(/\/agents\/[0-9a-f-]{36}$/, FIRST_COMPILE);
  await expect(page.getByRole("tab", { name: "Configuration" })).toBeVisible(
    FIRST_COMPILE,
  );

  const release = await holdApi(page);
  await page.reload();
  await expect(page.getByTestId("loading-agent-editor")).toBeVisible();
  await release();
  await expect(
    page.getByRole("heading", { name: "Skeleton agent", exact: true }),
  ).toBeVisible(FIRST_COMPILE);
  await expect(page.getByTestId("loading-agent-editor")).toHaveCount(0);

  // When the voice API fails, the skeleton gives way to a message with a way to try again, not a skeleton forever.
  await page.route("**/api/platform/**", (route) =>
    route.fulfill({ status: 500, body: "{}" }),
  );
  await page.goto("/voice-receptionist/variables");
  await expect(page.getByRole("button", { name: "Retry" })).toBeVisible(
    FIRST_COMPILE,
  );
  await expect(page.getByTestId("loading-variables")).toHaveCount(0);
});
