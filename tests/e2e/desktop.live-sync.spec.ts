import { expect, test } from "@playwright/test";
import { liveUrl } from "./helpers";

// Shift+N syncs, like the Sync button (Gmail's "update" key); a second press while one runs
// does not start another. The server's sync is answered by the test (no Gmail, no model).
test("Shift+N syncs once, says so, and shows in the shortcut list", async ({ page }) => {
  let calls = 0;
  let release: () => void = () => {};
  const held = new Promise<void>(r => { release = r; });
  await page.route("**/api/sync", async route => {
    calls += 1;
    await held;
    await route.fulfill({ status: 200, contentType: "application/json",
                          body: JSON.stringify({ synced: 3, removed: 1, triaged: 2, failed: 0 }) });
  });
  await page.goto(liveUrl());
  await expect(page.locator("#sync")).toHaveAttribute("title", /Shift\+N/);
  await page.keyboard.press("Shift+N");
  await expect(page.locator("#sync")).toBeDisabled();
  await expect(page.locator("#sync")).toHaveText("Syncing...");
  await page.keyboard.press("Shift+N");                       // already running: ignored
  release();
  await expect(page.locator("#syncnote")).toContainText("Synced 3, removed 1, ranked 2");
  await expect(page.locator("#sync")).toBeEnabled();
  expect(calls).toBe(1);
  await page.keyboard.press("?");
  await expect(page.locator("#help")).toContainText("Shift+N");
});

// While a search runs, it says it is searching Gmail and Slack, with both tabs, even when every
// Slack thread is marked done and none is on screen (the server's status says Slack is synced).
test("searching says Gmail and Slack while it runs, with no Slack thread on screen", async ({ page }) => {
  await page.route("**/api/items", async route => {
    const res = await route.fetch();
    const rows = (await res.json()).filter(r => r.item.source !== "slack");
    await route.fulfill({ response: res, body: JSON.stringify(rows) });
  });
  let release: () => void = () => {};
  const held = new Promise<void>(r => { release = r; });
  await page.route("**/api/search?*", async route => { await held; await route.continue(); });
  const status = page.waitForResponse(r => r.url().includes("/api/status"));
  await page.goto(liveUrl());
  expect((await (await status).json()).slack).toBe(true);
  await expect(page.locator("main li.card").first()).toBeVisible();
  await expect(page.locator("main li.card[data-id^='slack:']")).toHaveCount(0);
  await page.keyboard.press("/");
  await page.keyboard.type("invoice");
  await page.keyboard.press("Enter");
  const tabs = page.getByRole("tab");
  await expect(tabs.nth(1)).toHaveText(/Gmail\s*…/);
  await expect(tabs.nth(2)).toHaveText(/Slack\s*…/);
  await tabs.nth(1).click();
  await expect(page.getByRole("tabpanel").filter({ visible: true })).toContainText("Searching Gmail and Slack");
  release();
  await expect(tabs.nth(2)).toHaveText(/Slack\s*1/);
});
