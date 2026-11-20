import { test, expect, type Page } from "@playwright/test";

// The Meta call is replaced by a fake (clinic_voice_receptionist.testing.FakeWhatsAppGraph). Patient messages arrive
// on a separate service in production, so the conversation list is checked here empty; the stored, decrypted
// history is covered by the API tests (tests/test_whatsapp.py).
test.setTimeout(90_000);
const FIRST_COMPILE = { timeout: 30_000 };

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

test("staff switch between Voice and WhatsApp, connect a number and see no secret again", async ({
  page,
}) => {
  await signIn(page);
  await page.goto("/voice-receptionist");
  const channels = page.getByRole("navigation", { name: "Agent channels" });
  await channels.getByRole("link", { name: "WhatsApp" }).click();
  await expect(
    page.getByRole("heading", { name: "WhatsApp conversations" }),
  ).toBeVisible(FIRST_COMPILE);
  await expect(page.getByText("No conversations yet")).toBeVisible();
  await expect(page.getByTestId("voice-breadcrumb")).toContainText(
    "Conversations",
  );
  await expect(
    page.getByRole("link", { name: "Test studio", exact: true }),
  ).toHaveCount(0); // the Voice menu is gone while on the WhatsApp channel

  await page
    .getByRole("navigation", { name: "Workspace navigation" })
    .getByRole("link", { name: "Configuration" })
    .click();
  await expect(
    page.getByRole("heading", { name: "WhatsApp configuration" }),
  ).toBeVisible(FIRST_COMPILE);
  await expect(page.getByTestId("voice-breadcrumb")).toContainText(
    "Configuration",
  );

  const form = page.getByRole("form", { name: "WhatsApp settings" });
  await form.getByLabel("Phone number ID").fill("109876543210987");
  await form.getByLabel("Access token").fill("EAAB-browser-test-token");
  await form.getByLabel("Greeting").fill("Welcome to Browser Practice!");
  await expect(form.getByLabel("Search the knowledge base")).not.toBeChecked();
  await form.getByLabel("Search the knowledge base").check();
  await form.getByRole("button", { name: "Connect number" }).click();
  await expect(page.getByText("Agent on")).toBeVisible();
  await expect(page.getByText("+1 555 010 0000")).toBeVisible();

  await page.reload();
  const saved = page.getByRole("form", { name: "WhatsApp settings" });
  await expect(saved.getByLabel("Phone number ID")).toHaveValue(
    "109876543210987",
  );
  await expect(saved.getByLabel("Access token")).toHaveValue(""); // never sent back
  await expect(page.getByText("EAAB-browser-test-token")).toHaveCount(0);
  await expect(saved.getByLabel("Search the knowledge base")).toBeChecked();
  await expect(saved.getByLabel("Greeting")).toHaveValue(
    "Welcome to Browser Practice!",
  );

  // A saved account can be edited without typing the token again, and disconnected.
  await saved.getByLabel("Agent name").fill("Front desk on WhatsApp");
  await saved.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("WhatsApp settings saved")).toBeVisible();
  await saved.getByRole("button", { name: "Disconnect number" }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Disconnect" })
    .click();
  await expect(
    page
      .getByRole("form", { name: "WhatsApp settings" })
      .getByLabel("Access token"),
  ).toHaveAttribute("required", "");

  await page
    .getByRole("navigation", { name: "Agent channels" })
    .getByRole("link", { name: "Voice" })
    .click();
  await expect(page.getByTestId("voice-breadcrumb")).toContainText("Overview");
});

test("a long last message is cut short, so the Open button stays on screen", async ({
  page,
}) => {
  await signIn(page);
  const long = "Hello! Welcome to our clinic. ".repeat(12);
  await page.route("**/whatsapp/conversations", (route) =>
    route.fulfill({
      json: [
        {
          id: "11111111-1111-4111-8111-111111111111",
          contact_number: "918125122831",
          contact_name: "Vishnu",
          last_message_at: new Date().toISOString(),
          message_count: 2,
          last_message: long,
          last_direction: "outbound",
        },
      ],
    }),
  );
  for (const width of [1440, 820, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/voice-receptionist/whatsapp");
    const open = page.getByRole("button", {
      name: "Open the conversation with Vishnu",
    });
    await expect(open).toBeVisible(FIRST_COMPILE);
    const box = await open.boundingBox();
    expect(box!.x + box!.width).toBeLessThanOrEqual(width);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth + 1,
      ),
    ).toBeFalsy();
  }
});
