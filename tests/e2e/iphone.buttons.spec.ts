import { expect, test } from "@playwright/test";
import { card, GMAIL_ID, openDemo, rowPoint, tap } from "./helpers";

// The reply action row on a phone: every control (buttons, the Move to select and the Open in
// Gmail link) is thumb-sized, and the wrapped groups never push the page sideways.
test("reply action row: 44px targets, no sideways scroll", async ({ page }) => {
  await openDemo(page);
  const cdp = await page.context().newCDPSession(page);
  await tap(cdp, await rowPoint(card(page, GMAIL_ID)));
  const row = card(page, GMAIL_ID).locator(".detail .reply > .actions");
  await expect(row).toBeVisible();
  await row.scrollIntoViewIfNeeded();
  const hs = await row.locator(".btn, select, a").evaluateAll(ns => ns.map(n =>
    [(n.tagName + " " + (n.textContent || "").trim()).slice(0, 30), n.getBoundingClientRect().height] as [string, number]));
  expect(hs.length).toBeGreaterThanOrEqual(7);
  expect(hs.filter(([, h]) => h < 43.5), "controls under 44px").toEqual([]);
  const w = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth,
                                         client: document.documentElement.clientWidth }));
  expect(w.scroll, "page is wider than the phone").toBeLessThanOrEqual(w.client);
});
