import { expect, test } from "@playwright/test";
import { card, DEMO_THREADS, GMAIL_ID, GMAIL_ID_2, openDemo } from "./helpers";

// Keyboard on a desktop window, against the static demo. The first card is a Slack thread, so
// Gmail-only checks press j until the Signed SOW thread (the second card) is current.
test.describe("keyboard", () => {
  test.beforeEach(async ({ page }) => { await openDemo(page); });

  const current = "main li.card.current";

  test("j and k move the selection", async ({ page }) => {
    const cards = page.locator("main li.card");
    const first = await cards.nth(0).getAttribute("data-id");
    const second = await cards.nth(1).getAttribute("data-id");
    await page.keyboard.press("j");
    await expect(page.locator(current)).toHaveAttribute("data-id", first!);
    await page.keyboard.press("j");
    await expect(page.locator(current)).toHaveAttribute("data-id", second!);
    await page.keyboard.press("k");
    await expect(page.locator(current)).toHaveAttribute("data-id", first!);
    await expect(page.locator(current)).toHaveCount(1);
  });

  test("Enter opens the current thread", async ({ page }) => {
    await page.keyboard.press("j");
    await page.keyboard.press("j");
    const c = card(page, GMAIL_ID);
    await expect(c).toHaveClass(/current/);
    await page.keyboard.press("Enter");
    await expect(c.locator(":scope > .row")).toHaveAttribute("aria-expanded", "true");
    await expect(c.locator(".detail .thread-subject")).toHaveText(/Signed SOW/);
  });

  test("Enter again closes the thread; u only ever closes", async ({ page }) => {
    await page.keyboard.press("j");
    await page.keyboard.press("j");
    const row = card(page, GMAIL_ID).locator(":scope > .row");
    await page.keyboard.press("Enter");
    await expect(row).toHaveAttribute("aria-expanded", "true");
    await page.keyboard.press("Enter");
    await expect(row).toHaveAttribute("aria-expanded", "false");
    await page.keyboard.press("u");
    await expect(row).toHaveAttribute("aria-expanded", "false");
    await page.keyboard.press("o");
    await page.keyboard.press("u");
    await expect(row).toHaveAttribute("aria-expanded", "false");
  });

  test("e archives, the next thread becomes current, and Undo restores", async ({ page }) => {
    await page.keyboard.press("j");
    await page.keyboard.press("j");
    await page.keyboard.press("e");
    await expect(card(page, GMAIL_ID)).toHaveCount(0);
    await expect(page.locator(current)).toHaveAttribute("data-id", GMAIL_ID_2);
    const toast = page.locator("#toast");
    await expect(toast).toContainText("Archived: Signed SOW");
    await toast.getByRole("button", { name: "Undo" }).click();
    await expect(card(page, GMAIL_ID)).toHaveCount(1);
    await expect(page.locator("main li.card")).toHaveCount(DEMO_THREADS);
  });

  test("s stars and unstars the current thread", async ({ page }) => {
    await page.keyboard.press("j");
    await page.keyboard.press("j");
    const star = card(page, GMAIL_ID).locator(":scope > .star");
    await expect(star).toHaveAttribute("aria-pressed", "false");
    await page.keyboard.press("s");
    await expect(star).toHaveAttribute("aria-pressed", "true");
    await expect(star).not.toHaveClass(/pending/);
    await expect(page.locator("#counts .starview")).toHaveText(/1 Starred/);
    await page.keyboard.press("s");
    await expect(star).toHaveAttribute("aria-pressed", "false");
    await expect(page.locator("#counts .starview")).toHaveText(/0 Starred/);
  });

  test("? opens the shortcut list, which lists s; Esc closes it", async ({ page }) => {
    const help = page.locator("#help");
    await expect(help).toBeHidden();
    await page.keyboard.press("?");
    await expect(help).toBeVisible();
    await expect(help.locator("dt", { hasText: /^s$/ })).toHaveCount(1);
    await expect(help.locator("dt", { hasText: /^s$/ }).locator("+ dd")).toContainText("Star");
    await page.keyboard.press("Escape");
    await expect(help).toBeHidden();
  });

  test("the Starred toggle shows only starred threads, and back", async ({ page }) => {
    await page.keyboard.press("j");
    await page.keyboard.press("j");
    await page.keyboard.press("s");
    await expect(card(page, GMAIL_ID).locator(":scope > .star")).toHaveAttribute("aria-pressed", "true");
    await card(page, GMAIL_ID_2).locator(":scope > .star").click();
    await expect(card(page, GMAIL_ID_2).locator(":scope > .star")).toHaveAttribute("aria-pressed", "true");
    const toggle = page.locator("#counts .starview");
    await expect(toggle).toHaveText(/2 Starred/);
    await toggle.click();
    await expect(page.locator("main section h2")).toHaveText("Starred (2)");
    const ids = await page.locator("main li.card").evaluateAll(ls => ls.map(l => (l as HTMLElement).dataset.id));
    expect(ids.sort()).toEqual([GMAIL_ID, GMAIL_ID_2].sort());
    await page.locator("#counts .starview").click();              // now "Show all threads"
    await expect(page.locator("main li.card")).toHaveCount(DEMO_THREADS);
  });
});

// j never lands on a row inside a closed section (Ignore starts collapsed); one j past the last
// visible row opens that section and selects its first row; k walks back up from there.
test("j skips collapsed rows, then opens the next collapsed section", async ({ page }) => {
  await openDemo(page);
  const ignore = page.locator("main section details", { has: page.locator("summary", { hasText: /^Ignore \(\d+\)$/ }) });
  await expect(ignore).toHaveCount(1);
  expect(await ignore.evaluate(d => (d as HTMLDetailsElement).open)).toBe(false);
  const shown = await page.locator("main li.card").evaluateAll(ls =>
    ls.filter(l => !l.closest("details:not([open])")).map(l => (l as HTMLElement).dataset.id!));
  const firstIgnored = await ignore.locator("li.card").first().getAttribute("data-id");
  expect(shown.length).toBeGreaterThan(5);
  const cur = page.locator("main li.card.current");
  for (const id of shown) {
    await page.keyboard.press("j");
    await expect(cur).toHaveAttribute("data-id", id);
    expect(await cur.evaluate(l => !!l.closest("details:not([open])")), "selected a collapsed row").toBe(false);
  }
  await page.keyboard.press("j");
  await expect(cur).toHaveAttribute("data-id", firstIgnored!);
  expect(await cur.evaluate(l => !!l.closest("details:not([open])")), "selected a collapsed row").toBe(false);
  expect(await ignore.evaluate(d => (d as HTMLDetailsElement).open)).toBe(true);
  await expect(cur).toBeVisible();
  await expect(cur).toBeInViewport();
  await page.keyboard.press("k");
  await expect(cur).toHaveAttribute("data-id", shown[shown.length - 1]);
});
