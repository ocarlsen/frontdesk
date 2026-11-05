import { expect, test } from "@playwright/test";
import { card, GMAIL_ID, liveUrl, openDemo } from "./helpers";

// Account (top right, beside the counts) opens the Google account panel. It turns red once a Gmail sign-in has
// expired; the panel shows connected in green and anything else in red; and an action that
// failed for want of a sign-in offers Account in its message. The demo server has no Google
// account, so its answers are stubbed here.
const status = (login: boolean) => ({ at: "t1", changed_at: "c1", ok: true, summary: "synced 3", slack: true, login });

test("Account turns red on an expired sign-in and opens the panel with coloured states", async ({ page }) => {
  await page.route("**/api/status", r => r.fulfill({ json: status(true) }));
  await page.route("**/api/google", r => r.fulfill({ json: {
    desktop_client: true, web_client: false, generation: 1,
    read: true, read_expired: false, actions: false, actions_expired: true } }));
  await page.goto(liveUrl());
  const acct = page.locator("header #account");
  await expect(acct).toHaveText("\u25cf Account: sign in again");
  await expect(acct).toHaveClass(/attention/);
  await acct.click();
  const panel = page.locator("#profilepanel");
  await expect(panel.locator(".gstate.ok")).toHaveText("connected");
  await expect(panel.locator(".gstate.bad")).toHaveText("sign-in expired");
  await expect(panel.getByRole("button", { name: "Reconnect" })).toHaveCount(2);
});

test("Account stays plain when every sign-in is good", async ({ page }) => {
  await page.route("**/api/status", r => r.fulfill({ json: status(false) }));
  await page.goto(liveUrl());
  await expect(page.locator("main li.card").first()).toBeVisible();
  await expect(page.locator("header #account")).toHaveText("Account");
  await expect(page.locator("header #account")).not.toHaveClass(/attention/);
});

test("an archive that fails on sign-in offers Account, which opens the panel", async ({ page }) => {
  await page.route("**/api/action", r => r.fulfill({ status: 412, json: { error:
    "Gmail sign-in needed. Open Account (top right) to reconnect Gmail actions, or run " +
    "'bin/frontdesk authorize-actions' in a Terminal once." } }));
  await page.goto(liveUrl());
  await card(page, GMAIL_ID).locator(":scope > .row").click();
  await page.keyboard.press("e");
  const toast = page.locator("#toast");
  await expect(toast).toContainText("Archive failed: Gmail sign-in needed. Open Account (top right)");
  await toast.getByRole("button", { name: "Account" }).click();
  await expect(page.locator("#profilepanel")).toBeVisible();
  await expect(page.locator("#profilepanel h3")).toHaveText("Google account");
});

test("the static demo shows Account too, and its panel says connecting is off", async ({ page }) => {
  await openDemo(page);
  const acct = page.locator("header #account");
  await expect(acct).toHaveText("Account");
  await acct.click();
  await expect(page.locator("#profilepanel")).toContainText("Demo: connecting Gmail is off here.");
});
