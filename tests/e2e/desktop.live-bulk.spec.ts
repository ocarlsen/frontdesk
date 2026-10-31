import { expect, test } from "@playwright/test";
import { card, liveUrl } from "./helpers";

// Batch actions through the real server (tests/e2e/live_server.py, demo mode: the store side of
// each action runs, Gmail is skipped): every batch action and its Undo show a toast per thread,
// and the server's own list agrees after each step. Two FYI threads no other spec touches.
const A = "gmail:19a2f0c3b1d40007";   // Your Copperleaf order
const B = "gmail:19a2f0c3b1d4000f";   // Your October statement
const RESULT = "gmail:e2e0000000000c03";

test.describe.configure({ mode: "serial" });

async function recordToasts(page) {
  await page.evaluate(() => {
    const w = window as any;
    const real = w.toast;
    w.__toasts = [];
    w.toast = (...a: unknown[]) => { w.__toasts.push(String(a[0])); return real(...a); };
  });
  return async () => {
    const t: string[] = await page.evaluate(() => (window as any).__toasts.splice(0));
    return t;
  };
}

async function serverRow(page, id: string) {
  const res = await page.request.get(new URL("/api/items", liveUrl()).href);
  expect(res.ok()).toBe(true);
  const rows = await res.json();
  return rows.find(r => r.item.id === id) || null;
}

async function selectBoth(page) {
  for (const id of [A, B]) {
    await card(page, id).hover();
    await card(page, id).locator(".rowcheck").click();
  }
  await expect(page.locator("#selbar .selcount")).toContainText("2");
}

test.describe("batch actions and Undo (live server)", () => {
  test("star, move and archive two threads, each undone, with progress toasts both ways", async ({ page }) => {
    await page.goto(liveUrl());
    const said = await recordToasts(page);
    const steps: [string, () => Promise<void>, RegExp, (a: any) => boolean][] = [
      ["Starring", () => page.keyboard.press("s"), /Starred: 2 threads/, r => !!r.item.starred],
      ["Moving", async () => { await page.locator("#selbar .selmove").selectOption("needs_you"); },
       /Moved to Needs you: 2 threads/, r => r.triage.bucket === "needs_you"],
      ["Archiving", () => page.keyboard.press("e"), /Archived: 2 threads/, r => r === null],
    ];
    for (const [doing, act, done, changed] of steps) {
      if (!(await page.locator("#selbar").isVisible())) await selectBoth(page);
      await act();
      await expect(page.locator("#toast")).toContainText(done);
      let t = await said();
      expect(t.filter(x => x.startsWith(doing + " ")), t.join(" | ")).toEqual(
        [doing + " 1 of 2…", doing + " 2 of 2…"]);
      for (const id of [A, B]) expect(changed(await serverRow(page, id)), doing + " " + id).toBe(true);
      await page.keyboard.press("z");
      await expect(page.locator("#toast")).toContainText("Undone.");
      t = await said();
      expect(t.filter(x => x.startsWith("Undoing")), t.join(" | ")).toEqual(
        ["Undoing 1 of 2…", "Undoing 2 of 2…"]);
      for (const id of [A, B]) {
        const r = await serverRow(page, id);
        expect(r && !changed(r), "undone " + doing + " " + id).toBe(true);
      }
    }
    for (const id of [A, B]) {
      await expect(card(page, id).locator("xpath=ancestor::section")).toHaveAttribute("aria-label", "FYI");
    }
  });

  test("Move to inbox on a search result, then Undo, through the server", async ({ page }) => {
    await page.goto(liveUrl());
    await page.keyboard.press("/");
    await page.keyboard.type("receipts");
    await page.keyboard.press("Enter");
    await page.getByRole("tab").nth(1).click();
    const said = await recordToasts(page);
    await card(page, RESULT).hover();
    await card(page, RESULT).locator(".rowcheck").click();
    await page.locator("#selbar").getByRole("button", { name: "Move to inbox" }).click();
    await expect(page.locator("#toast")).toContainText("Moved to the inbox: 1 thread.");
    let t = await said();
    expect(t.filter(x => x.startsWith("Moving to the inbox ")), t.join(" | ")).toEqual(["Moving to the inbox 1 of 1…"]);
    const kept = await serverRow(page, RESULT);
    expect(kept && kept.item.kept && kept.item.labels.includes("INBOX")).toBe(true);   // stored, in the inbox
    await page.keyboard.press("z");
    await expect(page.locator("#toast")).toContainText("Undone.");
    t = await said();
    expect(t.filter(x => x.startsWith("Undoing")), t.join(" | ")).toEqual(["Undoing 1 of 1…"]);
    expect(await serverRow(page, RESULT)).toBeNull();                 // archived: off the list
  });

  test("the shortcut list fits a short window on the live page", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 560 });
    await page.goto(liveUrl());
    await page.keyboard.press("?");
    const box = page.locator("#help .helpbox");
    await expect(box).toBeVisible();
    const r = await box.boundingBox();
    expect(r!.y + r!.height).toBeLessThanOrEqual(560);
    const last = box.locator("dd").last();
    await last.scrollIntoViewIfNeeded();
    await expect(last).toBeInViewport();
  });
});
