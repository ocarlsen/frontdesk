import { expect, test } from "@playwright/test";
import { card, liveUrl } from "./helpers";

// Keep for Slack matches (tests/e2e/live_server.py's "receipts" answer adds two matches only
// these tests keep): the icon, and a selection through the bar, bring each conversation into
// FrontDesk; Undo marks them done. Each conversation is kept once, so these run in order.
const GROUP = "slack:G0E2E0002:dm";
const THREAD = "slack:C0E2E0003:1740000300.000100";

async function slackTab(page) {
  await page.goto(liveUrl());
  await page.keyboard.press("/");
  await page.keyboard.type("receipts");
  await page.keyboard.press("Enter");
  await page.getByRole("tab").nth(2).click();
}

async function serverRow(page, id: string) {
  const res = await page.request.get(new URL("/api/items", liveUrl()).href);
  return (await res.json()).find(r => r.item.id === id) || null;
}

test.describe.configure({ mode: "serial" });

test.describe("Keep for Slack matches (live server)", () => {
  test("select both with the checkbox and x; Keep brings them in; Undo marks them done", async ({ page }) => {
    await slackTab(page);
    await card(page, GROUP).hover();
    await card(page, GROUP).locator(".rowcheck").click();
    await card(page, THREAD).locator(":scope > .row").focus();
    await page.keyboard.press("x");
    const bar = page.locator("#selbar");
    await expect(bar.locator(".selcount")).toContainText("2");
    await bar.getByRole("button", { name: /^Keep/ }).click();
    await expect(page.locator("#toast")).toContainText("Kept: 2 conversations.");
    for (const id of [GROUP, THREAD]) {
      await expect(page.locator(`main li.card.result[data-id='${id}']`)).toHaveCount(0);   // left the matches
      const row = await serverRow(page, id);
      expect(row && row.item.kept, id + " stored and kept").toBe(true);
    }
    await page.keyboard.press("z");
    await expect(page.locator("#toast")).toContainText("Undone.");
    for (const id of [GROUP, THREAD]) expect(await serverRow(page, id), id + " done").toBeNull();
  });
});
