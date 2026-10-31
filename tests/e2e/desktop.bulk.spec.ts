import { expect, test } from "@playwright/test";
import { card, GMAIL_ID, GMAIL_ID_2, openDemo } from "./helpers";

// Bulk selection on the static demo: x and the checkbox select, the bar acts on the selection,
// the single-thread keys act on all of it, and one Undo reverses the batch.
test.describe("bulk selection", () => {
  test.beforeEach(async ({ page }) => {
    await openDemo(page);
    await page.keyboard.press("j");
    await page.keyboard.press("j");
    await expect(card(page, GMAIL_ID)).toHaveClass(/current/);
  });

  test("x selects two, the bar counts them, e archives both and z brings both back", async ({ page }) => {
    await page.keyboard.press("x");
    await page.keyboard.press("j");
    await page.keyboard.press("x");
    const bar = page.locator("#selbar");
    await expect(bar).toBeVisible();
    await expect(bar.locator(".selcount")).toHaveText("2 selected");
    const rows = await bar.locator(":scope > *").evaluateAll(ns =>
      new Set(ns.map(n => Math.round(n.getBoundingClientRect().top + n.getBoundingClientRect().height / 2))).size);
    expect(rows, "the bar keeps one line at 1280px").toBe(1);
    await page.keyboard.press("e");
    await expect(card(page, GMAIL_ID)).toHaveCount(0);
    await expect(card(page, GMAIL_ID_2)).toHaveCount(0);
    await expect(page.locator("#toast")).toContainText("2 threads");
    await expect(bar).toBeHidden();
    await page.keyboard.press("z");
    await expect(card(page, GMAIL_ID)).toHaveCount(1);
    await expect(card(page, GMAIL_ID_2)).toHaveCount(1);
  });

  test("checkbox and Shift-click select a range; the bar marks them unread and read", async ({ page }) => {
    const first = card(page, GMAIL_ID);
    await first.hover();
    await first.locator(".rowcheck").click();
    const third = page.locator("section[aria-label='Needs you'] li.card").nth(4);
    await third.hover();
    await third.locator(".rowcheck").click({ modifiers: ["Shift"] });
    const n = await page.locator("main li.card.selected").count();
    expect(n).toBeGreaterThanOrEqual(3);
    await page.locator("#selbar").getByRole("button", { name: "Mark read" }).click();
    await expect(page.locator("#toast")).toContainText(/Marked read|Already read/);
    await expect(first).not.toHaveClass(/unread/);
    await expect(first).toHaveClass(/selected/);             // the selection stays
    await page.keyboard.press("Escape");
    await first.hover();
    await first.locator(".rowcheck").click();
    await page.locator("#selbar").getByRole("button", { name: "Mark unread" }).click();
    await expect(page.locator("#toast")).toContainText("Marked unread: 1 thread.");
    await expect(first).toHaveClass(/unread/);
  });

  test("after clicking checkboxes, Shift+I and Shift+U act on the selection", async ({ page }) => {
    const rows = page.locator("section[aria-label='Needs you'] li.card");
    for (const i of [0, 1, 2]) {
      await rows.nth(i).hover();
      await rows.nth(i).locator(".rowcheck").click();       // focus stays on the checkbox
    }
    await expect(page.locator("#selbar .selcount")).toHaveText("3 selected");
    // While the batch runs, the toast says what is happening (record every toast it shows).
    await page.evaluate(() => {
      const w = window as any;
      const real = w.toast;
      w.__toasts = [];
      w.toast = (...a: unknown[]) => { w.__toasts.push(String(a[0])); return real(...a); };
    });
    await page.keyboard.press("Shift+U");
    await expect(page.locator("#toast")).toContainText(/Marked unread|Already unread/);
    const said: string[] = await page.evaluate(() => (window as any).__toasts);
    const changed = Number((said.join(" ").match(/Marked unread: (\d+)/) || [])[1] || 0);
    expect(said.filter(t => /^Marking unread \d of \d/.test(t)).length, said.join(" | ")).toBe(changed);
    expect(changed).toBeGreaterThan(0);
    for (const i of [0, 1, 2]) await expect(rows.nth(i)).toHaveClass(/unread/);
    // Marking read or unread keeps the selection, as in Gmail: act again without reselecting.
    for (const i of [0, 1, 2]) await expect(rows.nth(i)).toHaveClass(/selected/);
    await expect(page.locator("#selbar .selcount")).toHaveText("3 selected");
    await page.keyboard.press("Shift+I");
    await expect(page.locator("#toast")).toContainText("Marked read: 3 threads.");
    for (const i of [0, 1, 2]) await expect(rows.nth(i)).not.toHaveClass(/unread/);
    for (const i of [0, 1, 2]) await expect(rows.nth(i)).toHaveClass(/selected/);
    await page.keyboard.press("e");                          // archive takes them away: cleared
    await expect(page.locator("#selbar")).toBeHidden();
  });

  test("* a selects every row in view, * n clears, Esc clears", async ({ page }) => {
    await page.keyboard.press("*");
    await page.keyboard.press("a");
    const visible = await page.locator("main li.card").evaluateAll(ns =>
      ns.filter(n => (n as HTMLElement).offsetParent !== null && !n.closest("details:not([open])")).length);
    await expect(page.locator("main li.card.selected")).toHaveCount(visible);
    await page.keyboard.press("*");
    await page.keyboard.press("n");
    await expect(page.locator("#selbar")).toBeHidden();
    await page.keyboard.press("x");
    await expect(page.locator("#selbar")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator("main li.card.selected")).toHaveCount(0);
  });

  test("the bar moves the selection to another section", async ({ page }) => {
    await page.keyboard.press("x");
    await page.locator("#selbar .selmove").selectOption("fyi");
    await expect(card(page, GMAIL_ID).locator("xpath=ancestor::section")).toHaveAttribute("aria-label", "FYI");
    await expect(page.locator("#toast")).toContainText("Moved to FYI");
  });
});
