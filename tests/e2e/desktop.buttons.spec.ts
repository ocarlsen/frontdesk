import { expect, type Locator, test } from "@playwright/test";
import { card, GMAIL_ID, openDemo } from "./helpers";

// The reply action row's button system: one height for every control (the Move to select
// included), blue only for the one recommended action, secondary controls raised off the reply
// panel, a disabled Save sunk back to the panel grey, and the whole row on one line at desktop width
// for the demo's SOW thread.
async function openRow(page): Promise<Locator> {
  const c = card(page, GMAIL_ID);
  await c.locator(":scope > .row").click();
  const row = c.locator(".detail .reply > .actions");
  await expect(row).toBeVisible();
  return row;
}

const CONTROLS = ".btn, select";

test.describe("reply action row", () => {
  test.beforeEach(async ({ page }) => { await openDemo(page); });

  test("every control is one height, the Move to select as tall as Save", async ({ page }) => {
    const row = await openRow(page);
    const boxes = await row.locator(CONTROLS).evaluateAll(ns => ns.map(n => {
      const r = n.getBoundingClientRect();
      return { what: n.tagName + " " + (n.textContent || "").trim().slice(0, 20), h: r.height };
    }));
    expect(boxes.length).toBeGreaterThanOrEqual(6);
    const save = await row.getByRole("button", { name: "Save as Gmail draft" }).boundingBox();
    const pick = await row.locator("select.movepick").boundingBox();
    expect(Math.abs(pick!.height - save!.height), "Move to vs Save").toBeLessThanOrEqual(1);
    const hs = boxes.map(b => b.h);
    expect(Math.max(...hs) - Math.min(...hs), JSON.stringify(boxes)).toBeLessThanOrEqual(1);
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`secondary controls stand out from the reply panel (${scheme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      const row = await openRow(page);
      const panel = await page.locator(`li.card[data-id="${GMAIL_ID}"] .detail .reply`)
        .evaluate(n => getComputedStyle(n).backgroundColor);
      const fills = await row.locator(".btn:not(.primary):not([disabled]), select.movepick")
        .evaluateAll(ns => ns.map(n => ({
          what: n.tagName + " " + (n.textContent || "").trim().slice(0, 20),
          bg: getComputedStyle(n).backgroundColor })));
      expect(fills.length).toBeGreaterThanOrEqual(4);
      for (const f of fills) expect(f.bg, `${f.what} vs panel`).not.toBe(panel);
    });
  }

  test("a disabled Save sinks to the panel grey, not pale blue", async ({ page }) => {
    const row = await openRow(page);
    await page.locator(`li.card[data-id="${GMAIL_ID}"] .reply textarea`).fill("");
    const save = row.getByRole("button", { name: "Save as Gmail draft" });
    await expect(save).toBeDisabled();
    const look = (l: Locator) => l.evaluate(n => {
      const cs = getComputedStyle(n);
      return { bg: cs.backgroundColor, border: cs.borderTopColor, opacity: cs.opacity };
    });
    const accent = await page.evaluate(() => {
      const p = document.createElement("span");
      p.style.backgroundColor = "var(--accent)";
      document.body.append(p);
      const c = getComputedStyle(p).backgroundColor;
      p.remove();
      return c;
    });
    const s = await look(save);
    const neutral = await look(row.getByRole("button", { name: "Copy" }));
    const panel = await page.locator(`li.card[data-id="${GMAIL_ID}"] .detail .reply`)
      .evaluate(n => getComputedStyle(n).backgroundColor);
    expect(s.bg).toBe(panel);
    expect(s.bg).not.toBe(neutral.bg);
    expect(s.bg).not.toBe(accent);
    expect(s.border).toBe(neutral.border);
    expect(s.opacity).toBe("1");
    // Enabled again, it is the blue one.
    await page.locator(`li.card[data-id="${GMAIL_ID}"] .reply textarea`).fill("Thanks, signed.");
    await expect(save).toBeEnabled();
    expect((await look(save)).bg).toBe(accent);
  });

  test("the row stays on one line at 1280px", async ({ page }) => {
    const row = await openRow(page);
    const tops = await row.locator(".btn, select, a").evaluateAll(ns =>
      ns.map(n => Math.round(n.getBoundingClientRect().top + n.getBoundingClientRect().height / 2)));
    expect(tops.length).toBeGreaterThanOrEqual(7);
    expect(Math.max(...tops) - Math.min(...tops), "controls on different lines").toBeLessThanOrEqual(1);
  });
});
