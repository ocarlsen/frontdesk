import { expect, test } from "@playwright/test";
import { card, GMAIL_ID, liveUrl, openDemo } from "./helpers";

// Ask: the live demo server (tests/e2e/live_server.py) fills the box with its own question; the
// static demo has no model and says so. Neither test presses Ask, so nothing calls a model.
test("Ask starts with the server's question in the box (live demo server)", async ({ page }) => {
  const base = new URL(liveUrl());
  const res = await page.request.get(new URL("/api/ask?item=" + encodeURIComponent(GMAIL_ID), base).href);
  expect(res.ok()).toBe(true);
  const advise = (await res.json()).advise as string;
  expect(advise.trim().length).toBeGreaterThan(20);

  await page.goto(liveUrl());
  const c = card(page, GMAIL_ID);
  await c.locator(":scope > .row").click();
  await c.locator(".ask > summary").click();
  const box = c.getByRole("textbox", { name: "Your question about this thread" });
  await expect(box).toHaveValue(advise);
  await expect(c.locator(".ask").getByRole("button", { name: "Ask", exact: true })).toBeEnabled();
});

test("the static demo's Ask says it needs a live model", async ({ page }) => {
  await openDemo(page);
  const c = card(page, GMAIL_ID);
  await c.locator(":scope > .row").click();
  await c.locator(".ask > summary").click();
  await expect(c.locator(".ask .askbody")).toContainText("Demo: Ask needs a live model");
  await expect(c.locator(".ask textarea")).toHaveCount(0);
});
