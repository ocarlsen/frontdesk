import { expect, test } from "@playwright/test";
import { openDemo } from "./helpers";

// The search box on the static demo: / focuses it, typing filters the synced threads, Enter leaves
// the box (all-of-Gmail search is live-only, and says so), j/k move through matches, Esc clears.
test.describe("search", () => {
  test.beforeEach(async ({ page }) => { await openDemo(page); });

  test("/ focuses, typing filters, Enter then j/k, Esc restores the inbox", async ({ page }) => {
    const box = page.locator("#search");
    await page.keyboard.press("/");
    await expect(box).toBeFocused();
    await expect(box).toHaveValue("");
    await page.keyboard.type("order");
    const res = page.locator("section[aria-label='Search results']");
    await expect(res).toBeVisible();
    const cards = res.locator("li.card");
    const n = await cards.count();
    expect(n).toBeGreaterThanOrEqual(2);
    // Matches come from subjects and bodies alike; both order notices are among them, and the
    // list is a strict subset of the inbox.
    const subjects = await cards.locator(".subject").allTextContents();
    expect(subjects.some(s => s.includes("Copperleaf order"))).toBe(true);
    expect(n).toBeLessThan(await page.evaluate(() => (window as any).__items.length));
    await expect(page.locator("#counts")).toContainText(`${n} in FrontDesk`);
    await page.keyboard.press("Enter");
    await expect(box).not.toBeFocused();
    await expect(res).toContainText("runs against your own account in the live app");
    await page.keyboard.press("j");
    await expect(cards.first()).toHaveClass(/current/);
    await page.keyboard.press("j");
    await expect(cards.nth(1)).toHaveClass(/current/);
    await page.keyboard.press("Escape");
    await expect(res).toHaveCount(0);
    await expect(box).toHaveValue("");
    await expect(page.locator("section[aria-label='Needs you']")).toBeVisible();
  });

  test("Esc in the box clears it; / typed in a reply box stays text", async ({ page }) => {
    const box = page.locator("#search");
    await box.click();
    await page.keyboard.type("zzzz-nothing");
    await expect(page.locator("section[aria-label='Search results']")).toContainText("No synced thread matches.");
    await page.keyboard.press("Escape");
    await expect(box).toHaveValue("");
    await expect(page.locator("section[aria-label='Search results']")).toHaveCount(0);
    const first = page.locator("main li.card").first();
    await first.locator(":scope > .row").click();
    const ta = first.locator(".reply textarea");
    await ta.fill("");
    await ta.type("a/b");
    await expect(ta).toHaveValue("a/b");
    await expect(box).not.toBeFocused();
  });
});
