import { expect, test } from "@playwright/test";
import { liveUrl } from "./helpers";

// An open page checks the server's status every minute and reloads its list only after a sync
// that changed something: an unchanged sync must not re-render every open page every 15 minutes.
test("the page reloads after a changed sync, not after an unchanged one", async ({ page }) => {
  await page.clock.install();
  const answers = [
    { at: "t1", changed_at: "c1", ok: true, summary: "synced 3, ranked 0", slack: true },
    { at: "t2", changed_at: "c1", ok: true, summary: "synced 3, ranked 0; no change in Gmail", slack: true },
    { at: "t3", changed_at: "c3", ok: true, summary: "synced 3, ranked 1", slack: true },
  ];
  let n = 0;
  await page.route("**/api/status", route => {
    const body = answers[Math.min(n, answers.length - 1)];
    n += 1;
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  let loads = 0;
  page.on("request", r => { if (r.url().includes("/api/items")) loads += 1; });
  await page.goto(liveUrl());
  await expect.poll(() => n).toBe(1);
  await expect.poll(() => loads).toBe(1);                 // the first load
  await page.clock.runFor(60_000);                         // a sync ran, nothing changed
  await expect.poll(() => n).toBe(2);
  await page.waitForTimeout(200);
  expect(loads).toBe(1);
  await page.clock.runFor(60_000);                         // a sync that changed something
  await expect.poll(() => n).toBe(3);
  await expect.poll(() => loads).toBe(2);
});
