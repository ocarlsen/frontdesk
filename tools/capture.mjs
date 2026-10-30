// Screenshots for the site pages, with Playwright's Chromium (from tests/e2e; run `npm ci` there
// once). Exact viewport, deviceScaleFactor 2, so the image is exactly 2x the CSS size with no
// strip of unpainted pixels (Chrome's --screenshot flag had a viewport shorter than its window).
//
//   node tools/capture.mjs URL OUT.jpg|OUT.png WIDTH HEIGHT|auto [STAGE.js]
//
// STAGE.js is the body of an async function run in the page before the shot (open a thread,
// hide the rest). HEIGHT "auto" sizes the viewport to the staged page's full height, so nothing
// is cut off; if STAGE returns a number, that CSS height is used instead (to end on a clean
// edge). The page is settled first: fonts loaded, network idle, two animation frames.
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";

const require = createRequire(new URL("../tests/e2e/package.json", import.meta.url));
const { chromium } = require("@playwright/test");

const [url, out, w, h, stage] = process.argv.slice(2);
if (!url || !out || !w || !h) {
  console.error("usage: node tools/capture.mjs URL OUT.jpg WIDTH HEIGHT|auto [STAGE.js]");
  process.exit(2);
}
const width = Number(w);
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width, height: h === "auto" ? 800 : Number(h) },
                                       deviceScaleFactor: 2, colorScheme: "light" });
  page.on("pageerror", e => { console.error("page error:", e.message); process.exitCode = 1; });
  await page.goto(url, { waitUntil: "networkidle" });
  await page.locator("main li.card").first().waitFor();
  let staged = null;
  if (stage) {
    const body = readFileSync(stage, "utf-8");
    staged = await page.evaluate(`(async () => {\n${body}\n})()`);
  }
  await page.waitForLoadState("networkidle");
  const settle = () => page.evaluate(() => document.fonts.ready.then(() =>
    new Promise(ok => requestAnimationFrame(() => requestAnimationFrame(ok)))));
  await settle();
  if (h === "auto") {
    const full = typeof staged === "number" ? Math.ceil(staged)
      : await page.evaluate(() => Math.ceil(document.documentElement.scrollHeight));
    await page.setViewportSize({ width, height: full });
    await settle();
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await settle();
  const png = out.toLowerCase().endsWith(".png");   // the type follows OUT's extension
  await page.screenshot({ path: out, animations: "disabled",
                          ...(png ? { type: "png" } : { type: "jpeg", quality: 82 }) });
  console.log("wrote", out);
} finally {
  await browser.close();
}
