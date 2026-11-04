import { expect, type Page, test } from "@playwright/test";
import { card, GMAIL_ID, liveUrl } from "./helpers";

// Web images in a mail stay off until asked (a tracking pixel tells the sender you opened it).
// The demo inbox has no HTML mail, so the page's list gets one HTML message and /msg serves it.
async function openWithHtml(page: Page, html: string): Promise<void> {
  await page.route("**/api/items", async route => {
    const res = await route.fetch();
    const rows = await res.json();
    for (const r of rows) if (r.item.id === GMAIL_ID) r.item.messages[0].has_html = true;
    await route.fulfill({ response: res, json: rows });
  });
  await page.route("**/msg?*", route => route.fulfill({
    status: 200, contentType: "text/html; charset=utf-8", body: html,
    headers: { "Content-Security-Policy": "img-src data:" },
  }));
  await page.goto(liveUrl());
  const c = card(page, GMAIL_ID);
  await c.locator(":scope > .row").click();
  const full = c.locator("details.fullthread");
  if (!(await full.evaluate(d => (d as HTMLDetailsElement).open))) await full.locator("summary").click();
}

test("a mail with web images offers Show images, which reloads it with them", async ({ page }) => {
  await openWithHtml(page, '<p>News</p><img src="https://img.example.test/pixel.gif">');
  const c = card(page, GMAIL_ID);
  const bar = c.locator(".imagebar");
  await expect(bar).toContainText("Images are hidden.");
  const frame = c.locator("iframe.mailframe").first();
  expect(await frame.getAttribute("src")).not.toContain("images=1");
  await bar.getByRole("button", { name: "Show images" }).click();
  await expect(bar).toContainText("Images shown for this message.");
  expect(await frame.getAttribute("src")).toContain("images=1");
  await expect(c.locator(".imagebar")).toHaveCount(1);       // the reload adds no second bar
  // The demo server refuses to save settings, and the page says so rather than pretending.
  await bar.getByRole("button", { name: /^Always show from / }).click();
  await expect(page.locator("#toast")).toContainText("Couldn't save that: Demo mode");
});

test("a mail with no web images gets no bar", async ({ page }) => {
  await openWithHtml(page, '<p>Plain</p><img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=">');
  const c = card(page, GMAIL_ID);
  await expect(c.locator("iframe.mailframe").first()).toBeVisible();
  await page.waitForTimeout(300);
  await expect(c.locator(".imagebar")).toHaveCount(0);
});
