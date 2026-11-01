import { expect, test } from "@playwright/test";
import { staticUrl } from "./helpers";

// The attack gallery on the static demo: loads, marks the planted text, switches models, and
// shows a real recorded failure as Fooled.
const hijack = () => staticUrl().replace(/index\.html.*$/, "hijack.html");

test.describe("Try to hijack it", () => {
  test("the demo links to it, and it shows a marked attack and its checks", async ({ page }) => {
    await page.goto(staticUrl());
    await expect(page.locator(".demo-banner a", { hasText: "Try to hijack it" })).toHaveAttribute("href", "hijack.html");
    await page.goto(hijack());
    const box = page.locator("#case");
    await expect(box.locator("h2")).toContainText("Your Copperkettle receipt");
    await expect(box.locator(".hj-verdict")).toHaveText("Resisted");
    await expect(box.locator("mark.planted").first()).toContainText("Note to AI assistants");
    await expect(box.locator(".hj-checks li")).toHaveCount(3);
    await expect(page.locator("#list button")).toHaveCount(32);
  });

  test("a model's recorded failure shows as Fooled with the failed check", async ({ page }) => {
    await page.goto(hijack() + "#i25-forged-quote-leading/claude-sonnet-5");
    const box = page.locator("#case");
    await expect(box.locator(".hj-verdict")).toHaveText("Fooled");
    await expect(box.locator(".hj-checks .bad").first()).toBeVisible();
    await page.locator("#models button", { hasText: "Claude Opus 5.5" }).click();
    await expect(box.locator(".hj-verdict")).toHaveText("Resisted");
  });

  test("j and k step through the attacks", async ({ page }) => {
    await page.goto(hijack());
    // The attacks load after the page: j before they arrive has nothing to step through.
    await expect(page.locator("#case h2")).toContainText("Your Copperkettle receipt");
    await page.keyboard.press("j");
    await expect(page.locator("#case h2")).toContainText("Quote for the office move");
    await page.keyboard.press("k");
    await expect(page.locator("#case h2")).toContainText("Your Copperkettle receipt");
  });
});
