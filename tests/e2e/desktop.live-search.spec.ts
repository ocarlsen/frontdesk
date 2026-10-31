import { expect, test } from "@playwright/test";
import { card, liveUrl } from "./helpers";

// The search and Keep paths against the real server (tests/e2e/live_server.py), with synthetic
// fixtures in place of Gmail and Slack: a thread kept from a search and archived in Gmail, and
// fake search answers. One flow, in order, since each step changes the server's store.
const KEPT = "gmail:e2e0000000000a01";
const FOUND_1 = "gmail:e2e0000000000b01";
const FOUND_2 = "gmail:e2e0000000000b02";
const section = (page, name: string) => page.locator(`section[aria-label='${name}']`);

test.describe.configure({ mode: "serial" });

test.describe("search, Keep and Move to inbox (live server)", () => {
  test("a kept thread outside the inbox: Move to inbox, then Undo", async ({ page }) => {
    await page.goto(liveUrl());
    const c = card(page, KEPT);
    await expect(c.locator("xpath=ancestor::section")).toHaveAttribute("aria-label", "From search");
    await c.locator(":scope > .row").click();
    const actions = c.locator(".detail .replyactions");
    await expect(actions.getByRole("button", { name: "Archive" })).toHaveCount(0);   // not in the inbox
    await actions.getByRole("button", { name: "Move to inbox" }).click();
    await expect(page.locator("#toast")).toContainText("Moved to the inbox");
    await expect(card(page, KEPT).locator("xpath=ancestor::section")).not.toHaveAttribute("aria-label", "From search");
    await expect(card(page, KEPT).locator(".detail .replyactions").getByRole("button", { name: "Archive" })).toHaveCount(1);
    await page.keyboard.press("z");                                   // Undo archives it again
    await expect(card(page, KEPT)).toHaveCount(0);
  });

  test("search shows Gmail and Slack tabs; a result opens in place; Keep brings it in", async ({ page }) => {
    await page.goto(liveUrl());
    await page.keyboard.press("/");
    await page.keyboard.type("invoice");
    await page.keyboard.press("Enter");
    const tabs = page.getByRole("tab");
    await expect(tabs.nth(1)).toHaveText(/Gmail\s*2/);
    await expect(tabs.nth(2)).toHaveText(/Slack\s*1/);                // two matches, one thread
    await tabs.nth(1).click();
    const row = card(page, FOUND_1);
    await expect(row.locator(".dot")).toHaveAttribute("title", /Not ranked/);
    await row.locator(":scope > .row").click();
    await expect(row.locator(".detail")).toContainText("Synthetic body of: Old invoice from Harbor Supply.");
    await expect(row.locator("iframe")).toHaveCount(0);              // never sender HTML before Keep
    await row.getByRole("button", { name: "Keep in FrontDesk" }).click();
    await expect(page.locator("#toast")).toContainText("Kept");
    await expect(card(page, FOUND_1).locator("xpath=ancestor::section")).toHaveAttribute("aria-label", "From search");
    await page.keyboard.press("/");
    await page.keyboard.type("invoice");
    await page.keyboard.press("Enter");
    await page.getByRole("tab").nth(2).click();
    await expect(page.locator("main li.card.result").filter({ visible: true })).toHaveCount(1);
    await expect(page.getByRole("tabpanel").filter({ visible: true })).toContainText("#ops");
  });

  test("the bulk bar's Inbox moves kept threads back to the inbox", async ({ page }) => {
    await page.goto(liveUrl());
    await page.keyboard.press("/");
    await page.keyboard.type("lunch");
    await page.keyboard.press("Enter");
    await page.getByRole("tab").nth(1).click();
    await card(page, FOUND_2).locator(":scope > .row").click();
    await card(page, FOUND_2).getByRole("button", { name: "Keep in FrontDesk" }).click();
    await expect(card(page, FOUND_2).locator("xpath=ancestor::section")).toHaveAttribute("aria-label", "From search");
    const both = [FOUND_1, FOUND_2];
    for (const id of both) {
      await card(page, id).hover();
      await card(page, id).locator(".rowcheck").click();
    }
    const inbox = page.locator("#selbar").getByRole("button", { name: "Move to inbox" });
    await expect(inbox).toBeVisible();
    await inbox.click();
    await expect(page.locator("#toast")).toContainText("Moved to the inbox: 2 threads.");
    await expect(section(page, "From search")).toHaveCount(0);
    for (const id of both) await expect(card(page, id)).toHaveClass(/selected/);   // the selection stays
  });
});
