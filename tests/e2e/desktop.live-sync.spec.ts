import { expect, test } from "@playwright/test";
import { liveUrl } from "./helpers";

// The server's status, answered by the test: the last sync `agoMs` ago (null: never synced).
async function statusAt(page, agoMs: number | null) {
  await page.route("**/api/status", route => {
    const at = agoMs === null ? "" : new Date(Date.now() - agoMs).toISOString().replace(/\.\d+Z$/, "Z");
    return route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify({ at, changed_at: at, ok: true, summary: "synced 3, ranked 0", slack: true,
                             auto_sync_minutes: 15 }) });
  });
}
const freshStatus = (page) => statusAt(page, 10_000);

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
  await freshStatus(page);                                    // so opening the page does not sync
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

// Opening the page syncs when the last sync is more than 2 minutes old (or never ran), once,
// and not when it is fresh; a refusal from the server (here: demo mode) stays quiet.
for (const [name, ago, expected] of [["ten minutes old", 10 * 60_000, 1], ["never synced", null, 1],
                                     ["30 seconds old", 30_000, 0]] as const) {
  test(`opening the page with the last sync ${name} syncs ${expected ? "once" : "not at all"}`, async ({ page }) => {
    await statusAt(page, ago);
    let calls = 0;
    await page.route("**/api/sync", route => {
      calls += 1;
      return route.fulfill({ status: 200, contentType: "application/json",
                             body: JSON.stringify({ synced: 4, removed: 0, triaged: 1, failed: 0 }) });
    });
    await page.goto(liveUrl());
    await expect(page.locator("main li.card").first()).toBeVisible();
    if (expected) await expect(page.locator("#syncnote")).toContainText("Synced 4, removed 0, ranked 1");
    else await page.waitForTimeout(500);
    expect(calls).toBe(expected);
  });
}

test("a sync on open that the server refuses says nothing", async ({ page }) => {
  await statusAt(page, null);
  const refused = page.waitForResponse(r => r.url().includes("/api/sync"));
  await page.goto(liveUrl());                                // the live test server is in demo mode: 409
  expect((await refused).status()).toBe(409);
  await expect(page.locator("#sync")).toBeEnabled();
  await expect(page.locator("#syncnote")).not.toContainText("failed");
});

