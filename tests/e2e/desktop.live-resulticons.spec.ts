import { expect, test } from "@playwright/test";
import { card, liveUrl } from "./helpers";

// The icons under the age on each Gmail search result (tests/e2e/live_server.py's "receipts"):
// each matches that thread's own state, changes only once the server confirms, and the toast
// offers Undo. Slack matches have none: they are not stored, and open in Slack.
const NEW = "gmail:e2e0000000000c01";       // unread, in the inbox
const UNREAD_OLD = "gmail:e2e0000000000c04"; // unread, archived
const SLACK = "slack:C0E2E0001:1740000000.000100";

async function searchReceipts(page) {
  await page.goto(liveUrl());
  await page.keyboard.press("/");
  await page.keyboard.type("receipts");
  await page.keyboard.press("Enter");
  await page.getByRole("tab").nth(1).click();
  await expect(card(page, NEW)).toBeVisible();
}

const tool = (page, id: string, name: string) =>
  card(page, id).locator(":scope > .rowtools").getByRole("button", { name, exact: true });

test.describe.configure({ mode: "serial" });

test.describe("icons on Gmail search results (live server)", () => {
  test("each row's icons match its state, under the age", async ({ page }) => {
    await searchReceipts(page);
    await card(page, NEW).hover();
    await expect(tool(page, NEW, "Mark read")).toBeVisible();
    await expect(tool(page, NEW, "Archive")).toBeVisible();
    const when = await card(page, NEW).locator(".when").boundingBox();
    const tools = await card(page, NEW).locator(":scope > .rowtools").boundingBox();
    expect(Math.abs((tools!.x + tools!.width / 2) - (when!.x + when!.width / 2))).toBeLessThan(3);
    expect(tools!.y).toBeGreaterThan(when!.y);                        // under the age
    await card(page, UNREAD_OLD).hover();
    await expect(tool(page, UNREAD_OLD, "Mark read")).toBeVisible();  // archived, but unread
    await expect(tool(page, UNREAD_OLD, "Move to inbox")).toBeVisible();
  });

  test("Mark read and Archive flip after the server confirms; Undo flips back", async ({ page }) => {
    await searchReceipts(page);
    await card(page, NEW).hover();
    await tool(page, NEW, "Mark read").click();
    await expect(page.locator("#toast")).toContainText("Marked read: 1 thread.");
    await card(page, NEW).hover();
    await expect(tool(page, NEW, "Mark unread")).toBeVisible();
    await expect(card(page, NEW)).not.toHaveClass(/unread/);
    await tool(page, NEW, "Archive").click();
    await expect(page.locator("#toast")).toContainText("Archived: 1 thread.");
    await card(page, NEW).hover();
    await expect(tool(page, NEW, "Move to inbox")).toBeVisible();
    await page.keyboard.press("z");
    await expect(page.locator("#toast")).toContainText("Undone.");
    await card(page, NEW).hover();
    await expect(tool(page, NEW, "Archive")).toBeVisible();
  });

  test("a failed change leaves the icon as it was", async ({ page }) => {
    await searchReceipts(page);
    await page.route("**/api/action", route => route.fulfill({ status: 502, body: '{"error":"Gmail is down"}',
                                                               contentType: "application/json" }));
    await card(page, NEW).hover();
    await tool(page, NEW, "Mark read").click();
    await expect(page.locator("#toast")).toContainText("1 failed");
    await card(page, NEW).hover();
    await expect(tool(page, NEW, "Mark read")).toBeVisible();
    await expect(card(page, NEW)).toHaveClass(/unread/);
  });

  test("a Slack match has a Keep icon and no read or archive icons", async ({ page }) => {
    await searchReceipts(page);
    await page.getByRole("tab").nth(2).click();
    await card(page, SLACK).hover();
    await expect(tool(page, SLACK, "Keep in FrontDesk")).toBeVisible();
    await expect(card(page, SLACK).locator(":scope > .rowtools button")).toHaveCount(1);
    await expect(card(page, SLACK).locator(":scope > .row")).toHaveAttribute("title", "Open in Slack");
  });

  test("Move to inbox on an archived result keeps it and it leaves the results", async ({ page }) => {
    await searchReceipts(page);
    await card(page, UNREAD_OLD).hover();
    await tool(page, UNREAD_OLD, "Move to inbox").click();
    await expect(page.locator("#toast")).toContainText("Moved to the inbox: 1 thread.");
    await expect(page.locator(`main li.card.result[data-id='${UNREAD_OLD}']`)).toHaveCount(0);
  });
});
