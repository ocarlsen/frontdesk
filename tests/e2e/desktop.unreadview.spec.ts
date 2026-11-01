import { expect, test } from "@playwright/test";
import { openDemo } from "./helpers";

// The Unread view beside Starred: one list of every unread thread, Gmail and Slack; g then u
// opens it, its toggle and g then i go back.
test("the Unread view lists exactly the unread threads, and toggles back", async ({ page }) => {
  await openDemo(page);
  const toggle = page.locator("#counts .unreadview");
  const unreadInInbox = await page.locator("main li.card.unread").count();
  expect(unreadInInbox).toBeGreaterThan(0);
  await expect(toggle).toHaveText(new RegExp(`${unreadInInbox} Unread`));
  await toggle.click();
  const sec = page.locator("section[aria-label='Unread']");
  await expect(sec.locator("h2")).toHaveText(`Unread (${unreadInInbox})`);
  await expect(sec.locator("li.card")).toHaveCount(unreadInInbox);
  await expect(sec.locator("li.card:not(.unread)")).toHaveCount(0);
  await expect(page.locator("#counts .unreadview")).toHaveText("Show all threads");
  await page.locator("#counts .unreadview").click();
  await expect(page.locator("section[aria-label='Unread']")).toHaveCount(0);
  await page.keyboard.press("g");
  await page.keyboard.press("u");
  await expect(page.locator("section[aria-label='Unread']")).toBeVisible();
  await page.keyboard.press("g");
  await page.keyboard.press("i");
  await expect(page.locator("section[aria-label='Unread']")).toHaveCount(0);
  await page.keyboard.press("?");
  await expect(page.locator("#help")).toContainText("the Unread view");
});
