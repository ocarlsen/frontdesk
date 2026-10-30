import type { CDPSession, Locator, Page } from "@playwright/test";

// Ids from the synthetic demo (frontdesk/demo_data). The static demo's state lives only in the
// tab (archive, star and done are JS maps in app.js), so every test's fresh page starts from
// the same untouched inbox.
export const GMAIL_ID = "gmail:19a2f0c3b1d40011";       // Signed SOW, Needs you
export const GMAIL_ID_2 = "gmail:19a2f0c3b1d40002";     // the Gmail thread after it
export const SLACK_ID = "slack:D01BENALEX:dm";            // a Slack DM (channel ids follow the clock)
export const DEMO_THREADS = 24;

export function staticUrl(): string {
  const u = process.env.FD_STATIC_URL;
  if (!u) throw new Error("FD_STATIC_URL unset: run through playwright.config.ts (global setup)");
  return u;
}

export function liveUrl(): string {
  const u = process.env.FD_LIVE_URL;
  if (!u) throw new Error("FD_LIVE_URL unset: run through playwright.config.ts (global setup)");
  return u;
}

export function card(page: Page, id: string): Locator {
  return page.locator(`main li.card[data-id="${id}"]`);
}

export async function openDemo(page: Page): Promise<void> {
  await page.goto(staticUrl());
  await page.locator("main li.card").first().waitFor();
}

type Pt = { x: number; y: number };

// A real touch gesture: Chromium's own input pipeline (CDP Input.dispatchTouchEvent) turns
// these into touch and pointer events, hit-testing, touch-action and scrolling included, so the
// page sees what a finger would produce. `hold` stops before touchEnd (for mid-swipe checks).
export async function touchPath(cdp: CDPSession, from: Pt, to: Pt, steps = 8,
                                opts: { hold?: boolean } = {}): Promise<void> {
  await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [from] });
  for (let i = 1; i <= steps; i++) {
    const x = from.x + ((to.x - from.x) * i) / steps;
    const y = from.y + ((to.y - from.y) * i) / steps;
    await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x, y }] });
  }
  if (!opts.hold) await touchEnd(cdp);
}

export async function touchEnd(cdp: CDPSession): Promise<void> {
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
}

export async function tap(cdp: CDPSession, at: Pt): Promise<void> {
  await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [at] });
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
}

// Where a gesture on a card's row starts: right of centre, so a left swipe has room to travel.
export async function rowPoint(c: Locator, fx = 0.8): Promise<Pt> {
  const row = c.locator(":scope > .row");
  await row.scrollIntoViewIfNeeded();
  const b = await row.boundingBox();
  if (!b) throw new Error("row has no box");
  return { x: b.x + b.width * fx, y: b.y + b.height / 2 };
}
