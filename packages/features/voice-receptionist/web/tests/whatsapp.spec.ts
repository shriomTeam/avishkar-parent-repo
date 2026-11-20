import { createHmac, randomUUID } from "node:crypto";
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

// Plays the part of Meta: posts a signed webhook call straight to the test API, as the WhatsApp service would receive it.
const API = "http://127.0.0.1:8001";
async function patientWrites(page: Page, phoneId: string, text: string) {
  const body = JSON.stringify({
    object: "whatsapp_business_account",
    entry: [
      {
        changes: [
          {
            value: {
              metadata: { phone_number_id: phoneId },
              contacts: [
                { wa_id: "15550001111", profile: { name: "Pat Patient" } },
              ],
              messages: [
                {
                  from: "15550001111",
                  id: `wamid.${randomUUID()}`,
                  type: "text",
                  text: { body: text },
                },
              ],
            },
          },
        ],
      },
    ],
  });
  const signature =
    "sha256=" +
    createHmac("sha256", "browser-test-app-secret").update(body).digest("hex");
  const response = await page.request.post(`${API}/whatsapp/webhook`, {
    data: body,
    headers: {
      "Content-Type": "application/json",
      "X-Hub-Signature-256": signature,
    },
  });
  expect(response.status()).toBe(200);
}

test("staff take over a chat: reply, the agent pauses, patient messages wait, then resume", async ({
  page,
}) => {
  await signIn(page);
  const phoneId = String(Math.floor(1e14 + Math.random() * 9e14));
  await page.goto("/voice-receptionist/whatsapp/settings");
  const form = page.getByRole("form", { name: "WhatsApp settings" });
  await form.getByLabel("Phone number ID").fill(phoneId, FIRST_COMPILE);
  await form.getByLabel("Access token").fill("EAAB-browser-test-token");
  await form.getByRole("button", { name: "Connect number" }).click();
  await expect(page.getByText("Agent on")).toBeVisible();

  await patientWrites(page, phoneId, "Can I move my visit?");
  await page.goto("/voice-receptionist/whatsapp");
  const open = page.getByRole("button", {
    name: "Open the conversation with Pat Patient",
  });
  await open.click(FIRST_COMPILE);
  const thread = page.getByTestId("whatsapp-thread");
  await expect(thread).toContainText("Can I move my visit?");
  await expect(thread).toContainText("Agent reply to: Can I move my visit?");
  await expect(page.getByTestId("whatsapp-agent-state")).toHaveText("Agent on");

  // A staff reply is sent, labelled as staff, and pauses the agent.
  const reply = page.getByRole("form", { name: "Reply to this person" });
  await reply.getByLabel("Reply").fill("Yes, tomorrow at 10 works.");
  await reply.getByRole("button", { name: "Send" }).click();
  await expect(
    thread.locator('[data-sender="staff"]', {
      hasText: "Yes, tomorrow at 10 works.",
    }),
  ).toBeVisible();
  await expect(thread.locator('[data-sender="staff"]')).toContainText(
    "(staff)",
  );
  await expect(page.getByTestId("whatsapp-agent-state")).toHaveText(
    "Agent paused",
  );
  await expect(reply.getByLabel("Reply")).toHaveValue("");
  await expect(
    page.getByRole("button", { name: "Resume agent" }),
  ).toBeVisible();

  // The patient writes again: the message is saved, and the agent stays silent.
  await patientWrites(page, phoneId, "Great, thank you");
  await page
    .getByRole("button", { name: "Close", exact: true })
    .first()
    .click();
  await expect(page.getByText("Needs reply")).toBeVisible(); // the list shows a chat waiting for a person
  await expect(page.getByText("Agent paused")).toBeVisible();
  await open.click();
  await expect(thread).toContainText("Great, thank you");
  await expect(thread).not.toContainText("Agent reply to: Great, thank you");

  // Resume: the agent answers the next message again.
  await page.getByRole("button", { name: "Resume agent" }).click();
  await expect(page.getByTestId("whatsapp-agent-state")).toHaveText("Agent on");
  await patientWrites(page, phoneId, "One more question");
  await page
    .getByRole("button", { name: "Close", exact: true })
    .first()
    .click();
  await open.click();
  await expect(thread).toContainText("Agent reply to: One more question");
});
