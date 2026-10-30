import { expect, type Page, test } from "@playwright/test";
import { card, GMAIL_ID, openDemo, rowPoint, tap } from "./helpers";

// Phone layout: no sideways page scroll, thumb-sized targets, header labels whole.
async function noSidewaysScroll(page: Page) {
  const w = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth,
    inner: window.innerWidth,
  }));
  expect(w.client).toBe(393);
  expect(w.scroll, "page is wider than the phone").toBeLessThanOrEqual(w.client);
}

// Every visible button-like target: [label, width, height, minimum]. 44 px is Apple's minimum;
// .btn.small is 40 as implemented in app.css.
async function targets(page: Page, scope: string) {
  return page.evaluate(sel => {
    const out: [string, number, number, number][] = [];
    for (const n of document.querySelectorAll<HTMLElement>(sel)) {
      if (!n.offsetParent) continue;
      const r = n.getBoundingClientRect();
      const min = n.classList.contains("small") ? 40 : 44;
      out.push([(n.className + " " + (n.textContent || "")).trim(), r.width, r.height, min]);
    }
    return out;
  }, scope);
}

test.describe("phone layout", () => {
  test.beforeEach(async ({ page }) => { await openDemo(page); });

  test("no horizontal page scroll in the list or an open thread", async ({ page }) => {
    await noSidewaysScroll(page);
    const cdp = await page.context().newCDPSession(page);
    await tap(cdp, await rowPoint(card(page, GMAIL_ID)));
    await expect(card(page, GMAIL_ID).locator(".detail")).toBeVisible();
    await page.locator(".detail .fullthread > summary").first().click();
    await noSidewaysScroll(page);
  });

  test("stars and action buttons are thumb-sized", async ({ page }) => {
    const cdp = await page.context().newCDPSession(page);
    await tap(cdp, await rowPoint(card(page, GMAIL_ID)));
    await expect(card(page, GMAIL_ID).locator(".detail")).toBeVisible();
    const all = await targets(page, "header .btn, main .card > .star, main .detail .actions .btn");
    expect(all.filter(t => t[0].startsWith("star")).length).toBeGreaterThan(5);
    expect(all.filter(t => t[0].includes("btn-archive")).length).toBe(1);
    const small = all.filter(([, w, h, min]) => w < min - 0.5 || h < min - 0.5);
    expect(small, "targets under the minimum").toEqual([]);
  });

  test("header labels never break inside a word", async ({ page }) => {
    const broken = await page.evaluate(() => {
      const bad: string[] = [];
      const walk = document.createTreeWalker(document.querySelector("header.top")!,
                                             NodeFilter.SHOW_TEXT);
      for (let n = walk.nextNode(); n; n = walk.nextNode()) {
        const parent = n.parentElement!;
        if (!parent.offsetParent && parent.tagName !== "H1") continue;
        const text = n.textContent || "";
        for (const m of text.matchAll(/\S+/g)) {
          const r = document.createRange();
          r.setStart(n, m.index!);
          r.setEnd(n, m.index! + m[0].length);
          const lines = new Set([...r.getClientRects()].filter(x => x.width > 0)
            .map(x => Math.round(x.top)));
          if (lines.size > 1) bad.push(m[0]);
        }
      }
      return bad;
    });
    expect(broken).toEqual([]);
    // And the labels are there to check: Memory, Profile, Sync and the counts.
    await expect(page.locator("header.top")).toContainText("Memory");
    await expect(page.locator("#counts")).toContainText("Needs you");
  });
});
