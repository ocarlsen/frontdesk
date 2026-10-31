import { expect, test } from "@playwright/test";
import { card, liveUrl } from "./helpers";

// Selecting Gmail search results (tests/e2e/live_server.py's "receipts" answer): x and the
// checkboxes select them, and the bar acts on each in Gmail by thread id ("result" actions),
// storing nothing, except Move to inbox, which also keeps the thread so it shows in FrontDesk.
// Slack matches are not selectable. The server is in demo mode, so the label
// change itself is a no-op there; tests/test_result_ops.py covers the Gmail call.
const NEW = "gmail:e2e0000000000c01";    // unread, in the inbox
const OLD = "gmail:e2e0000000000c02";    // read, archived
const SLACK = "slack:C0E2E0001:1740000000.000100";

async function searchReceipts(page) {
  await page.goto(liveUrl());
  await page.keyboard.press("/");
  await page.keyboard.type("receipts");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("tab").nth(1)).toHaveText(/Gmail\s*\d/);   // 1 once the first test kept OLD
  await page.getByRole("tab").nth(1).click();
  await expect(card(page, NEW)).toBeVisible();
}

function resultOps(page) {
  const ops: string[] = [];
  page.on("request", req => {
    if (!req.url().endsWith("/api/action") || req.method() !== "POST") return;
    const body = req.postDataJSON();
    if (body.kind === "result") ops.push(body.op + " " + body.item_id);
    else if (body.kind === "keep") ops.push("keep " + body.item_id);
  });
  return ops;
}

// Serial: the first test keeps a result, which turns it into a stored thread on the shared server.
test.describe.configure({ mode: "serial" });

test.describe("selecting Gmail search results (live server)", () => {
  test("x and the checkbox select results; the bar marks read, archives and moves to the inbox", async ({ page }) => {
    const ops = resultOps(page);
    await searchReceipts(page);
    await card(page, NEW).locator(":scope > .row").focus();          // makes it the current row
    await page.keyboard.press("x");
    await expect(card(page, NEW)).toHaveClass(/selected/);
    await card(page, OLD).hover();
    await card(page, OLD).locator(".rowcheck").click();
    const bar = page.locator("#selbar");
    await expect(bar.locator(".selcount")).toContainText("2");
    await expect(bar.getByRole("button", { name: /Keep/ })).toHaveCount(0);   // Inbox keeps
    await expect(bar.locator(".selmove")).toHaveCount(0);            // results are not ranked

    await page.keyboard.press("Shift+I");                            // only the unread one changes
    await expect(page.locator("#toast")).toContainText("Marked read: 1 thread.");
    await expect(card(page, NEW)).not.toHaveClass(/unread/);
    for (const id of [NEW, OLD]) await expect(card(page, id)).toHaveClass(/selected/);

    await page.keyboard.press("e");                                  // archives the one in the inbox
    await expect(page.locator("#toast")).toContainText("Archived: 1 thread.");
    await expect(card(page, NEW)).toContainText("Archived");
    await expect(bar).toBeHidden();
    await page.keyboard.press("z");                                  // Undo puts it back
    await expect(page.locator("#toast")).toContainText("Undone.");
    await expect(card(page, NEW)).toContainText("In the inbox");

    // Move to inbox on an archived result also keeps it: it leaves the results and is in FrontDesk.
    await card(page, OLD).hover();
    await card(page, OLD).locator(".rowcheck").click();
    await bar.getByRole("button", { name: "Move to inbox" }).click();
    await expect(page.locator("#toast")).toContainText("Moved to the inbox: 1 thread.");
    await expect(page.locator(`main li.card.result[data-id='${OLD}']`)).toHaveCount(0);
    await page.keyboard.press("Escape");
    await page.keyboard.press("Escape");                             // back to the inbox
    const kept = card(page, OLD);
    await expect(kept).toBeVisible();
    await expect(kept.locator("xpath=ancestor::section")).not.toHaveAttribute("aria-label", "From search");

    expect(ops).toEqual([`read ${NEW}`, `archive ${NEW}`, `inbox ${NEW}`, `inbox ${OLD}`, `keep ${OLD}`]);
  });

  test("Slack matches have no checkbox and x does not select them", async ({ page }) => {
    await searchReceipts(page);
    await page.getByRole("tab").nth(2).click();
    const s = card(page, SLACK);
    await expect(s).toBeVisible();
    await expect(s.locator(".rowcheck")).toHaveCount(0);
    await s.locator(":scope > .row").focus();
    await page.keyboard.press("x");
    await expect(s).not.toHaveClass(/selected/);
    await expect(page.locator("#selbar")).toBeHidden();
  });

  test("star from the bar", async ({ page }) => {
    const ops = resultOps(page);
    await searchReceipts(page);
    await card(page, NEW).hover();
    await card(page, NEW).locator(".rowcheck").click();
    await page.keyboard.press("s");
    await expect(page.locator("#toast")).toContainText("Starred: 1 thread.");
    await expect(card(page, NEW)).toHaveClass(/selected/);
    expect(ops).toEqual([`star ${NEW}`]);
  });
});
