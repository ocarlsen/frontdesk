import { expect, test } from "@playwright/test";
import { card, DEMO_THREADS, GMAIL_ID, openDemo, rowPoint, SLACK_ID, tap, touchEnd,
         touchPath } from "./helpers";

// Swipe left to archive (Gmail) or mark done (Slack), driven by real touch input through CDP.
test.describe("swipe on a phone", () => {
  test.beforeEach(async ({ page }) => { await openDemo(page); });

  test("a long left swipe archives, shows Undo, and Undo brings it back", async ({ page }) => {
    const cdp = await page.context().newCDPSession(page);
    const c = card(page, GMAIL_ID);
    const p = await rowPoint(c);
    await touchPath(cdp, p, { x: p.x - 220, y: p.y + 4 }, 10);
    await expect(c).toHaveCount(0);
    const toast = page.locator("#toast");
    await expect(toast).toBeVisible();
    await expect(toast).toContainText("Archived: Signed SOW");
    await toast.getByRole("button", { name: "Undo" }).click();
    await expect(c).toHaveCount(1);
    await expect(page.locator("main li.card")).toHaveCount(DEMO_THREADS);
  });

  test("a short left swipe snaps back and keeps the row", async ({ page }) => {
    const cdp = await page.context().newCDPSession(page);
    const c = card(page, GMAIL_ID);
    const p = await rowPoint(c);
    await touchPath(cdp, p, { x: p.x - 45, y: p.y }, 6, { hold: true });
    await expect(c).toHaveClass(/swiping/);          // it did follow the finger
    await expect(c).not.toHaveClass(/armed/);
    await touchEnd(cdp);
    await expect(c).not.toHaveClass(/swiping/);
    await expect(c).toHaveCount(1);
    expect(await c.evaluate(li => (li as HTMLElement).style.getPropertyValue("--swipe"))).toBe("");
    await expect(page.locator("#toast")).toBeHidden();
  });

  test("a mostly vertical drag scrolls the list and archives nothing", async ({ page }) => {
    const cdp = await page.context().newCDPSession(page);
    const c = card(page, GMAIL_ID);
    const p = await rowPoint(c, 0.5);
    expect(await page.evaluate(() => window.scrollY)).toBe(0);
    // Record whether the row ever started following the finger sideways during the drag.
    await c.evaluate(li => {
      const w = window as unknown as { __slid: boolean };
      w.__slid = false;
      new MutationObserver(() => { if (li.classList.contains("swiping")) w.__slid = true; })
        .observe(li, { attributes: true, attributeFilter: ["class"] });
    });
    await touchPath(cdp, p, { x: p.x - 30, y: p.y - 300 }, 12);
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(100);
    await expect(c).toHaveCount(1);
    await expect(c).not.toHaveClass(/swiping|leaving/);
    expect(await page.evaluate(() => (window as unknown as { __slid: boolean }).__slid),
           "the row slid sideways during a vertical drag").toBe(false);
    await expect(page.locator("main li.card")).toHaveCount(DEMO_THREADS);
    await expect(page.locator("#toast")).toBeHidden();
  });

  test("a tap opens the thread; the tap ending a swipe does not", async ({ page }) => {
    const cdp = await page.context().newCDPSession(page);
    const c = card(page, GMAIL_ID);
    const row = c.locator(":scope > .row");
    const p = await rowPoint(c);
    await touchPath(cdp, p, { x: p.x - 45, y: p.y }, 6);   // short swipe, finger lifts
    await page.waitForTimeout(500);
    await expect(row).toHaveAttribute("aria-expanded", "false");
    await expect(c.locator(".detail")).toHaveCount(0);
    await tap(cdp, await rowPoint(c));
    await expect(row).toHaveAttribute("aria-expanded", "true");
    await expect(c.locator(".detail")).toBeVisible();
  });

  test("a Slack row says Done, not Archive, and a swipe marks it done", async ({ page }) => {
    const cdp = await page.context().newCDPSession(page);
    const c = card(page, SLACK_ID);
    const p = await rowPoint(c);
    await touchPath(cdp, p, { x: p.x - 60, y: p.y }, 6, { hold: true });
    await expect(c.locator(".swipe-reveal")).toHaveText("Done");
    await touchEnd(cdp);
    await page.waitForTimeout(450);    // a swipe swallows clicks for 400 ms; then tap to open
    await tap(cdp, await rowPoint(c));
    const actions = c.locator(".detail .actions").first();
    await expect(actions.getByRole("button", { name: "Done", exact: true })).toBeVisible();
    await expect(actions.getByRole("button", { name: "Archive" })).toHaveCount(0);
    const p2 = await rowPoint(c);
    await touchPath(cdp, p2, { x: p2.x - 220, y: p2.y }, 10);
    await expect(c).toHaveCount(0);
    await expect(page.locator("#toast")).toContainText("Done: hidden until someone posts again");

    const g = card(page, GMAIL_ID);                          // and a Gmail row says Archive
    const q = await rowPoint(g);
    await touchPath(cdp, q, { x: q.x - 60, y: q.y }, 6, { hold: true });
    await expect(g.locator(".swipe-reveal")).toHaveText("Archive");
    await touchEnd(cdp);
  });
});
