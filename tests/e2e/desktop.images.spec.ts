import { expect, test } from "@playwright/test";
import { card, openDemo } from "./helpers";
import { readFileSync } from "node:fs";
import { join } from "node:path";

// The static demo's newsletter points at web images hosted on the demo site itself. They stay
// off until asked; Show images swaps in the message's exported -images page. Requests to the
// real host are answered from the repo's copy, so the test never leaves the machine.
const NEWSLETTER = "gmail:19a2f0c3b1d4000c";
const IMG = join(__dirname, "../../frontdesk/demo_data/img");

test("the demo newsletter's images stay off until Show images, then load", async ({ page }) => {
  const fetched: string[] = [];
  await page.route("https://frontdesk.ocarlsen.com/img/**", route => {
    const name = new URL(route.request().url()).pathname.split("/").pop() as string;
    fetched.push(name);
    return route.fulfill({ body: readFileSync(join(IMG, name)),
                           contentType: name.endsWith(".svg") ? "image/svg+xml" : "image/gif" });
  });
  await openDemo(page);
  await page.locator("main section summary", { hasText: /^Ignore \(\d+\)$/ }).click();   // starts collapsed
  const c = card(page, NEWSLETTER);
  await c.locator(":scope > .row").click();
  const full = c.locator("details.fullthread");
  if (!(await full.evaluate(d => (d as HTMLDetailsElement).open))) await full.locator("summary").click();
  const bar = c.locator(".imagebar");
  await expect(bar).toContainText("Images are hidden.");
  const frame = c.locator("iframe.mailframe").first();
  expect(await frame.getAttribute("src")).toMatch(/-0\.html$/);
  await page.waitForTimeout(300);
  expect(fetched).toEqual([]);                                // blocked: nothing fetched
  await bar.getByRole("button", { name: "Show images" }).click();
  await expect(bar).toContainText("Images shown for this message.");
  expect(await frame.getAttribute("src")).toMatch(/-0-images\.html$/);
  await expect.poll(() => fetched.sort()).toEqual(["open.gif", "weekly-diff-banner.svg"]);
  const banner = page.frameLocator(`li.card[data-id="${NEWSLETTER}"] iframe.mailframe`).locator("img").first();
  await expect.poll(() => banner.evaluate(i => (i as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  // Always show lasts for this tab only, like a star.
  await bar.getByRole("button", { name: /^Always show from / }).click();
  await expect(bar).toContainText("always show.");
  await bar.getByRole("button", { name: "Stop showing them" }).click();
  await expect(bar).toContainText("Images are hidden.");
  expect(await frame.getAttribute("src")).toMatch(/-0\.html$/);
});
