import { expect, test } from "@playwright/test";
import { card, GMAIL_ID, openDemo } from "./helpers";

// "Move to" is one drop-down showing the thread's current section; changing it moves the thread
// at once, with an Undo that moves it back. `v` focuses it from the keyboard.
test.describe("move to", () => {
  test.beforeEach(async ({ page }) => { await openDemo(page); });

  test("the drop-down shows the current section and moves with undo", async ({ page }) => {
    const c = card(page, GMAIL_ID);
    await c.locator(":scope > .row").click();
    const pick = c.locator("select.movepick");
    await expect(pick).toHaveValue("needs_you");
    await expect(c.locator(".moveto button")).toHaveCount(0);   // the old per-section buttons are gone
    await pick.selectOption("fyi");
    const fyi = page.locator("section", { has: page.locator("h2", { hasText: "FYI" }) });
    await expect(fyi.locator(`li.card[data-id="${GMAIL_ID}"]`)).toHaveCount(1);
    const toast = page.locator("#toast");
    await expect(toast).toContainText("Moved to FYI");
    await toast.getByRole("button", { name: "Undo" }).click();
    const needs = page.locator("section", { has: page.locator("h2", { hasText: "Needs you" }) });
    await expect(needs.locator(`li.card[data-id="${GMAIL_ID}"]`)).toHaveCount(1);
  });

  test("v opens the thread and focuses Move to", async ({ page }) => {
    await page.keyboard.press("j");
    await page.keyboard.press("j");
    await expect(card(page, GMAIL_ID)).toHaveClass(/current/);
    await page.keyboard.press("v");
    await expect(card(page, GMAIL_ID).locator("select.movepick")).toBeFocused();
    await page.keyboard.press("Escape");
    await page.keyboard.press("?");
    await expect(page.locator("#help")).toContainText("Move to another section");
  });
});
