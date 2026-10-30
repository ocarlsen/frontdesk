import { expect, test } from "@playwright/test";
import { card, GMAIL_ID_2, liveUrl, openDemo } from "./helpers";

// The People strip: a chip per person between the subject and the summary. Notes need the API,
// so the editor checks run on the live demo server (its memory is read-only, and nothing here
// presses Save); the static demo shows the chips read-only.
const IGNORE_ID = "gmail:19a2f0c3b1d40010";   // the phishing test, in Ignore

test("the strip sits above the subject; chips show addresses; a chip opens one editor and Escape closes it", async ({ page }) => {
  await page.goto(liveUrl());
  const c = card(page, GMAIL_ID_2);
  await c.locator(":scope > .row").click();
  const strip = c.locator(".detail .peoplestrip");
  await expect(strip).toBeVisible();
  const chips = strip.locator(".personchip");
  await expect(chips).toHaveText(["dana.whitfield@example.com · add note", "ines.moreau@example.com · add note"]);
  await expect(strip).not.toContainText(/\(\d+\)/);
  const y = async (sel: string) => (await c.locator(sel).first().boundingBox())!.y;
  expect(await y(".detail .peoplestrip")).toBeLessThan(await y(".detail .thread-subject"));
  expect(await y(".detail .thread-subject")).toBeLessThan(await y(".detail .summary"));
  await expect(c.locator(".peoplelabel")).toHaveText("People");

  await chips.nth(0).click();
  const editor = strip.locator(".personeditor");
  await expect(editor).toHaveCount(1);
  await expect(editor.getByRole("textbox", { name: "Note on dana.whitfield@example.com" })).toBeVisible();
  await expect(editor.getByRole("button", { name: "Save" })).toBeVisible();
  await chips.nth(1).click();
  await expect(editor).toHaveCount(1);
  await expect(editor.getByRole("textbox", { name: "Note on ines.moreau@example.com" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(editor).toHaveCount(0);
  await expect(chips.nth(1)).toBeFocused();
  // Escape from inside the note box closes it too.
  await chips.nth(0).click();
  await editor.locator("textarea").click();
  await page.keyboard.press("Escape");
  await expect(editor).toHaveCount(0);
});

test("Ask has no notes section any more", async ({ page }) => {
  await page.goto(liveUrl());
  const c = card(page, GMAIL_ID_2);
  await c.locator(":scope > .row").click();
  await c.locator(".ask > summary").click();
  await expect(c.getByRole("textbox", { name: "Your question about this thread" })).toBeVisible();
  await expect(c.locator(".ask")).not.toContainText("Your notes on these people");
  await expect(c.locator(".ask .personeditor, .ask textarea[placeholder^='What should FrontDesk remember']")).toHaveCount(0);
});

test("static demo: chips are read-only; an Ignore thread starts as a People link", async ({ page }) => {
  await openDemo(page);
  const c = card(page, GMAIL_ID_2);
  await c.locator(":scope > .row").click();
  const chip = c.locator(".peoplestrip .personchip").first();
  await expect(chip).toHaveText("dana.whitfield@example.com · add note");
  await expect(chip).toBeDisabled();
  await expect(chip).toHaveAttribute("title", /own copy/);

  await page.locator("section details > summary", { hasText: "Ignore" }).click();
  const ig = card(page, IGNORE_ID);
  await ig.locator(":scope > .row").click();
  const strip = ig.locator(".peoplestrip");
  await expect(strip.locator(".personchip")).toHaveCount(0);
  await strip.getByRole("button", { name: "People", exact: true }).click();
  await expect(strip.locator(".personchip")).toHaveText(["it-servicedesk@examp1e-corp.example.net · add note"]);
});
