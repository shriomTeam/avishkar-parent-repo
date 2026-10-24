import { expect, test } from "@playwright/test";

test("an invited account joins, loses access and accepts a re-invitation into the same membership", async ({
  browser,
  page,
  request,
}) => {
  await page.goto("/login");
  await page.getByRole("link", { name: "Continue with Google" }).click();
  await page.getByLabel("Workspace name").fill("Invitation Workspace");
  await page
    .getByRole("button", { name: "Create workspace", exact: true })
    .click();
  await expect(page).toHaveURL(/\/$/);
  await page
    .getByRole("button", { name: "Account menu for Browser Owner" })
    .click();
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await page.getByRole("tab", { name: "User management" }).click();
  // Existing-member conflicts explain the safe next step inside the drawer.
  await page.getByRole("button", { name: "Invite user", exact: true }).click();
  const existingMemberDrawer = page.getByRole("dialog", {
    name: "Invite user",
  });
  await existingMemberDrawer
    .getByLabel("Email address")
    .fill("browser@example.com");
  await existingMemberDrawer
    .getByRole("button", { name: "Send invitation" })
    .click();
  await expect(existingMemberDrawer.getByRole("alert")).toContainText(
    "This email already belongs to a workspace member.",
  );
  await existingMemberDrawer
    .getByRole("button", { name: "Cancel", exact: true })
    .click();
  // The test provider uses a fresh Google subject for every login with this email.
  // Invite another matching email identity; the owner workspace's email already belongs
  // to its current member, so use the test session helper to create a distinct owner email.
  const owner = await page.request.get("/api/v1/auth/me");
  const auth = await owner.json();
  await page.request.post("http://127.0.0.1:8001/_test/owner-email", {
    data: { user_id: auth.user.id, email: `owner-${auth.user.id}@example.com` },
  });
  await page.getByRole("button", { name: "Invite user", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "Invite user" });
  await drawer.getByLabel("Email address").fill("browser@example.com");
  await drawer.getByRole("button", { name: "Send invitation" }).click();
  await expect(drawer).toHaveCount(0);
  await expect(
    page.getByRole("cell", { name: "pending", exact: true }),
  ).toBeVisible();
  const captured = await request.get("http://127.0.0.1:8001/_test/emails");
  const messages: { to: string; text: string }[] = await captured.json();
  const message = messages
    .filter((m) => m.to === "browser@example.com")
    .at(-1)!;
  expect(message).toBeTruthy();
  const link = message.text.match(/https?:\/\/\S+\/invite#token=\S+/)![0];
  const recipient = await browser.newContext();
  const guest = await recipient.newPage();
  await guest.goto(link);
  await guest.getByRole("link", { name: "Continue with Google" }).click();
  await expect(
    guest.getByRole("heading", { name: "Join Invitation Workspace" }),
  ).toBeVisible();
  await expect(guest).toHaveURL(/\/invite$/);
  await guest
    .getByRole("button", { name: "Accept invitation", exact: true })
    .click();
  await expect(guest).toHaveURL(/\/$/);
  await expect(guest.getByTestId("clinic-name")).toHaveText(
    "Invitation Workspace",
  );
  await expect(
    guest.getByRole("link", { name: "Import data", exact: true }),
  ).toHaveCount(0);
  const me = await guest.request.get("/api/v1/auth/me");
  const joined = await me.json();
  expect(joined.workspace.id).toBe(auth.workspace.id);
  expect(joined.memberships).toHaveLength(1);
  expect(joined.memberships[0].role).toBe("front_desk");
  // Direct requests cannot grant management access just because the page hides it.
  const denied = await guest.request.get(
    `/api/v1/workspaces/${auth.workspace.id}/members`,
  );
  expect(denied.status()).toBe(403);
  await page.getByRole("tab", { name: "Workspace", exact: true }).click();
  await page.getByRole("tab", { name: "User management" }).click();
  await page.getByRole("button", { name: "Manage Browser Owner" }).click();
  page.once("dialog", (dialog) => dialog.accept());
  await page
    .getByRole("button", { name: "Remove access", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect((await guest.request.get("/api/platform/me")).status()).toBe(403);
  const beforeRemoval = await page.request.get(
    `/api/v1/workspaces/${auth.workspace.id}/members`,
  );
  const removedMember = (await beforeRemoval.json()).find(
    (m: { user_id: string }) => m.user_id === joined.user.id,
  );
  await page
    .getByRole("button", { name: "Re-invite Browser Owner", exact: true })
    .click();
  const reinvite = page.getByRole("dialog", { name: "Re-invite member" });
  await expect(reinvite.getByLabel("Email address")).toHaveValue(
    "browser@example.com",
  );
  await expect(reinvite.getByLabel("Email address")).toHaveAttribute(
    "readonly",
    "",
  );
  await reinvite.getByRole("button", { name: "Send invitation" }).click();
  await expect(reinvite).toHaveCount(0);
  expect((await guest.request.get("/api/platform/me")).status()).toBe(403);
  const redelivery = await request.get("http://127.0.0.1:8001/_test/emails");
  const resent = ((await redelivery.json()) as { to: string; text: string }[])
    .filter((m) => m.to === "browser@example.com")
    .at(-1)!;
  const freshLink = resent.text.match(/https?:\/\/\S+\/invite#token=\S+/)![0];
  expect(freshLink).not.toBe(link);
  await guest.goto(freshLink);
  await guest
    .getByRole("button", { name: "Accept invitation", exact: true })
    .click();
  await expect(guest).toHaveURL(/\/$/);
  const restored = await guest.request.get("/api/v1/auth/me");
  const restoredAuth = await restored.json();
  expect(restoredAuth.user.id).toBe(joined.user.id);
  expect(restoredAuth.workspace.id).toBe(auth.workspace.id);
  expect(restoredAuth.memberships).toHaveLength(1);
  const afterRestore = await page.request.get(
    `/api/v1/workspaces/${auth.workspace.id}/members`,
  );
  const returned = (await afterRestore.json()).filter(
    (m: { user_id: string }) => m.user_id === joined.user.id,
  );
  expect(returned).toHaveLength(1);
  expect(returned[0].id).toBe(removedMember.id);
  expect(returned[0].active).toBe(true);
  await recipient.close();
});
