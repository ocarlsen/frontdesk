import { expect, test } from "@playwright/test";
import { liveUrl } from "./helpers";

// The People strip on a phone (live demo server, so the chips are tappable): chips wrap inside
// the card, every chip is a 44 px target, and the page never scrolls sideways.
test("People chips wrap, are thumb-sized and keep the page phone-wide", async ({ page }) => {
  await page.goto(liveUrl());
  // The Slack thread with two people, one with a long display name.
  const c = page.locator("main li.card", { hasText: "#analytics-vendor" });
  await c.locator(":scope > .row").tap();
  const chips = c.locator(".peoplestrip .personchip");
  await expect(chips).toHaveCount(2);
  await expect(chips.nth(1)).toHaveText("Theo Park (Stonebridge Metrics) · add note");
  const boxes = await chips.evaluateAll(ns => ns.map(n => n.getBoundingClientRect().toJSON()));
  for (const b of boxes) {
    expect(b.height, "chip under 44 px").toBeGreaterThanOrEqual(44 - 0.5);
    expect(b.right, "chip past the screen edge").toBeLessThanOrEqual(393);
  }
  expect(boxes[1].top, "chips wrap onto a second line").toBeGreaterThan(boxes[0].top);
  await chips.nth(0).tap();
  await expect(c.locator(".personeditor textarea")).toBeVisible();
  const w = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth,
                                         client: document.documentElement.clientWidth }));
  expect(w.client).toBe(393);
  expect(w.scroll, "page is wider than the phone").toBeLessThanOrEqual(w.client);
});
