import { expect, test } from "@playwright/test";
import { openDemo } from "./helpers";

// One selection on screen: clicking a row makes it current, and j/k move both the current-row
// marker and keyboard focus, so a focus ring never stays behind on the row that was clicked.
test("after a click, j moves the selection and the focus together", async ({ page }) => {
  await openDemo(page);
  const cards = page.locator("main li.card");
  const third = cards.nth(2);
  const fourth = cards.nth(3);
  await third.locator(":scope > .row").click();          // opens it and makes it current
  await expect(third).toHaveClass(/current/);
  await third.locator(":scope > .row").click();          // close it again; focus stays on its row
  await page.keyboard.press("j");
  await expect(fourth).toHaveClass(/current/);
  await expect(page.locator("main li.card.current")).toHaveCount(1);
  await expect(fourth.locator(":scope > .row")).toBeFocused();
  await page.keyboard.press("k");
  await expect(third).toHaveClass(/current/);
  await expect(third.locator(":scope > .row")).toBeFocused();
});

// One indicator: the current-row bar. A focused row is always the current row, so the browser's
// focus ring is turned off rather than shown as a second box.
test("focusing a row makes it current, and no second focus ring is drawn", async ({ page }) => {
  await openDemo(page);
  const cards = page.locator("main li.card");
  const row2 = cards.nth(1).locator(":scope > .row");
  await row2.focus();
  await expect(cards.nth(1)).toHaveClass(/current/);
  await expect(page.locator("main li.card.current")).toHaveCount(1);
  await page.keyboard.press("j");
  const focused = cards.nth(2).locator(":scope > .row");
  await expect(focused).toBeFocused();
  expect(await focused.evaluate(el => getComputedStyle(el).outlineStyle)).toBe("none");
});
