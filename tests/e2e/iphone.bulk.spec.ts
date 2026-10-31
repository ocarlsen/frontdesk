import { expect, test } from "@playwright/test";
import { card, GMAIL_ID, GMAIL_ID_2, openDemo, rowPoint, tap, touchEnd } from "./helpers";

// On a phone: a long press selects, taps then add to the selection, and the bar docks at the
// bottom with thumb-sized buttons.
test("long press selects, taps add, the bar docks at the bottom", async ({ page }) => {
  await openDemo(page);
  const cdp = await page.context().newCDPSession(page);
  const c = card(page, GMAIL_ID);
  const p = await rowPoint(c);
  await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [p] });
  await page.waitForTimeout(700);
  await touchEnd(cdp);
  await expect(c).toHaveClass(/selected/);
  await expect(c.locator(":scope > .row")).toHaveAttribute("aria-expanded", "false");   // not opened
  // A row near the bottom sits behind the bar until scrolled up, as on a real phone.
  await card(page, GMAIL_ID_2).evaluate(e => e.scrollIntoView({ block: "center" }));
  await tap(cdp, await rowPoint(card(page, GMAIL_ID_2)));
  await expect(card(page, GMAIL_ID_2)).toHaveClass(/selected/);
  const bar = page.locator("#selbar");
  await expect(bar.locator(".selcount b")).toHaveText("2");
  const box = await bar.boundingBox();
  const vh = page.viewportSize()!.height;
  expect(Math.round(box!.y + box!.height)).toBeGreaterThanOrEqual(vh - 2);
  for (const h of await bar.locator(".btn").evaluateAll(ns => ns.map(n => n.getBoundingClientRect().height))) {
    expect(h).toBeGreaterThanOrEqual(44);
  }
});
