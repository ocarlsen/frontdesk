import { expect, test } from "@playwright/test";
import { card, GMAIL_ID, openDemo } from "./helpers";

// On a phone the selection bar docks at the bottom: the current row and the last rows stay
// above it.
test("selecting on a phone keeps the rows above the bottom bar", async ({ page }) => {
  await openDemo(page);
  const c = card(page, GMAIL_ID);
  await c.locator(".rowcheck").evaluate((el: HTMLInputElement) => el.click());
  const bar = page.locator("#selbar");
  await expect(bar).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  const barTop = (await bar.boundingBox())!.y;
  const last = (await page.locator("main li.card:visible").last().boundingBox())!;
  expect(last.y + last.height, "the last row clears the bar").toBeLessThanOrEqual(barTop);
  await c.scrollIntoViewIfNeeded();
  await c.evaluate((el: HTMLElement) => el.scrollIntoView({ block: "nearest" }));
  const b = (await c.boundingBox())!;
  expect(b.y + b.height).toBeLessThanOrEqual(barTop);
});
