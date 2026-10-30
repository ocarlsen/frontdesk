import { expect, test } from "@playwright/test";
import { card, GMAIL_ID, openDemo, SLACK_ID } from "./helpers";

// The static demo's threads are synthetic, so Open in Gmail / Slack must not leave for a real
// Gmail account chooser or a dead Slack host. They keep the link look and explain themselves.
test.describe("open links in the static demo", () => {
  test.beforeEach(async ({ page }) => { await openDemo(page); });

  for (const [id, where] of [[GMAIL_ID, "Gmail"], [SLACK_ID, "Slack"]] as const) {
    test(`Open in ${where} shows a toast and stays on the page`, async ({ page, context }) => {
      const c = card(page, id);
      await c.locator(":scope > .row").click();
      const link = c.locator(".detail a.openlink");
      await expect(link).toHaveText(`Open in ${where}`);
      await expect(link).toHaveAttribute("title", new RegExp(`live app.*${where}`));
      const before = page.url();
      const pages = context.pages().length;
      await link.click();
      await expect(page.locator("#toast")).toContainText(`in the live app this opens the thread in ${where}`);
      expect(page.url().replace(/#$/, "")).toBe(before.replace(/#$/, ""));
      expect(context.pages().length).toBe(pages);
    });
  }
});
