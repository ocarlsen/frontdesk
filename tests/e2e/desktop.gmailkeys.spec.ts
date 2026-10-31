import { expect, test } from "@playwright/test";
import { card, GMAIL_ID, GMAIL_ID_2, openDemo } from "./helpers";

// Gmail's keys on the static demo, and the hover tools that give each one a visible control.
const current = "main li.card.current";

test.describe("Gmail keys", () => {
  test.beforeEach(async ({ page }) => {
    await openDemo(page);
    await page.keyboard.press("j");
    await page.keyboard.press("j");
    await expect(card(page, GMAIL_ID)).toHaveClass(/current/);
  });

  test("Shift+U marks unread, z undoes it, Shift+I marks read", async ({ page }) => {
    const c = card(page, GMAIL_ID);
    const wasUnread = await c.evaluate(li => li.classList.contains("unread"));
    if (wasUnread) await page.keyboard.press("Shift+I");
    await expect(c).not.toHaveClass(/unread/);
    await page.keyboard.press("Shift+U");
    await expect(c).toHaveClass(/unread/);
    await expect(page.locator("#toast")).toContainText("Marked unread.");
    await page.keyboard.press("z");
    await expect(c).not.toHaveClass(/unread/);
  });

  test("e archives and z brings it back", async ({ page }) => {
    await page.keyboard.press("e");
    await expect(card(page, GMAIL_ID)).toHaveCount(0);
    await page.keyboard.press("z");
    await expect(card(page, GMAIL_ID)).toHaveCount(1);
  });

  test("] archives and opens the thread below", async ({ page }) => {
    await page.keyboard.press("Enter");
    await page.keyboard.press("]");
    await expect(card(page, GMAIL_ID)).toHaveCount(0);
    const next = card(page, GMAIL_ID_2);
    await expect(next).toHaveClass(/current/);
    await expect(next.locator(":scope > .row")).toHaveAttribute("aria-expanded", "true");
  });

  test("g then s shows Starred, g then i goes back", async ({ page }) => {
    await page.keyboard.press("g");
    await page.keyboard.press("s");
    await expect(page.locator("section[aria-label='Starred']")).toBeVisible();
    await page.keyboard.press("g");
    await page.keyboard.press("i");
    await expect(page.locator("section[aria-label='Needs you']")).toBeVisible();
  });

  test("a opens the reply with Reply all ticked", async ({ page }) => {
    await page.keyboard.press("a");
    const c = card(page, GMAIL_ID);
    await expect(c.locator(".replyall-box")).toBeChecked();
    await expect(c.locator(".reply textarea")).toBeFocused();
  });

  test("the current row shows its tools, each naming its key", async ({ page }) => {
    const tools = page.locator(current).locator(".rowtools");
    await expect(tools).toBeVisible();
    await expect(tools.locator("button").last()).toHaveAttribute("title", "Archive (e)");
    // The tools sit under the time and the checkbox under the dot: both stay visible.
    const row = page.locator(current);
    const box = async (sel: string) => (await row.locator(sel).first().boundingBox())!;
    await expect(row.locator(".when")).toBeVisible();
    await expect(row.locator(".dot")).toBeVisible();
    expect((await box(".rowtools")).y).toBeGreaterThanOrEqual((await box(".when")).y + (await box(".when")).height - 1);
    expect((await box(".rowcheck")).y).toBeGreaterThanOrEqual((await box(".dot")).y + (await box(".dot")).height);
    // Centred: the tools on the time, the checkbox on the dot (within 2px).
    const mid = (b: { x: number; width: number }) => b.x + b.width / 2;
    expect(Math.abs(mid(await box(".rowtools")) - mid(await box(".when")))).toBeLessThanOrEqual(2);
    expect(Math.abs(mid(await box(".rowcheck")) - mid(await box(".dot")))).toBeLessThanOrEqual(2);
    await expect(tools.locator(".btn-read")).toHaveAttribute("title", /Mark (read|unread) \(Shift\+[IU]\)/);
    await page.keyboard.press("?");
    await expect(page.locator("#help")).toContainText("Shift+I / Shift+U");
  });

test("the shortcut list fits a short window and scrolls to its last line", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 600 });
  await openDemo(page);
  await page.keyboard.press("?");
  const box = page.locator("#help .helpbox");
  await expect(box).toBeVisible();
  const r = await box.boundingBox();
  expect(r!.y).toBeGreaterThanOrEqual(0);
  expect(r!.y + r!.height).toBeLessThanOrEqual(600);
  const last = box.locator("dd").last();
  await last.scrollIntoViewIfNeeded();
  await expect(last).toBeInViewport();
});
});
