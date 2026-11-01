import { expect, test } from "@playwright/test";
import { openDemo } from "./helpers";

// Moving with j keeps room below the current row (about a row), so it never sits on the window's
// bottom edge, and k keeps it clear of the top (and of the sticky selection bar while selecting).
// A short window, so the list overflows and every step scrolls.
async function currentBox(page) {
  const b = (await page.locator("li.card.current").boundingBox())!;
  const h = await page.evaluate(() => innerHeight);
  return { top: b.y, bottom: b.y + b.height, h };
}

test.use({ viewport: { width: 1280, height: 600 } });

test("j leaves room below the current row, k leaves room above", async ({ page }) => {
  await openDemo(page);
  const steps = await page.locator("main li.card:visible").count();
  for (let i = 0; i < steps; i++) {
    await page.keyboard.press("j");
    const { top, bottom, h } = await currentBox(page);
    expect(bottom, `step ${i}: bottom ${bottom} of ${h}`).toBeLessThanOrEqual(h - 80);
    expect(top).toBeGreaterThanOrEqual(0);
  }
  for (let i = 0; i < 8; i++) {
    await page.keyboard.press("k");
    const { top } = await currentBox(page);
    expect(top, `k step ${i}`).toBeGreaterThanOrEqual(12);
  }
});

test("while selecting, the current row stays clear of the sticky selection bar", async ({ page }) => {
  await openDemo(page);
  await page.keyboard.press("j");
  await page.keyboard.press("x");
  const bar = page.locator("#selbar");
  await expect(bar).toBeVisible();
  for (let i = 0; i < 12; i++) await page.keyboard.press("j");
  for (let i = 0; i < 10; i++) {
    await page.keyboard.press("k");
    const barBox = (await bar.boundingBox())!;
    const { top, bottom, h } = await currentBox(page);
    expect(top, `k step ${i}: top ${top} under bar ending ${barBox.y + barBox.height}`)
      .toBeGreaterThanOrEqual(barBox.y + barBox.height);
    expect(bottom).toBeLessThanOrEqual(h);
  }
});

test("clicking a row near the bottom edge opens it (focus does not scroll it away)", async ({ page }) => {
  await openDemo(page);
  const h = await page.evaluate(() => innerHeight);
  // Find a row whose top is within the bottom 80px of the window, as a click target there.
  const id = await page.evaluate((h) => {
    for (const li of document.querySelectorAll("main li.card")) {
      const r = (li as HTMLElement).getBoundingClientRect();
      if (r.top > h - 80 && r.top < h - 20) return (li as HTMLElement).dataset.id;
    }
    // None there yet: scroll so the first row below the fold starts 50px above the bottom.
    for (const li of document.querySelectorAll("main li.card")) {
      const r = (li as HTMLElement).getBoundingClientRect();
      if (r.top > h) { window.scrollBy(0, r.top - (h - 50)); return (li as HTMLElement).dataset.id; }
    }
    return null;
  }, h);
  expect(id).toBeTruthy();
  const row = page.locator(`main li.card[data-id="${id}"] > .row`);
  const box = (await row.boundingBox())!;
  expect(box.y).toBeGreaterThan(h - 90);                      // really near the bottom edge
  await page.mouse.click(box.x + 200, box.y + 10);
  await expect(row).toHaveAttribute("aria-expanded", "true");
});
