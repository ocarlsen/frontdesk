// demo/film.ts: the FrontDesk tour film on the About page, recorded with TourKit (not yet public).
//
//   node <TourKit>/run.ts demo/film.ts --check   dry run: every caption, nothing recorded
//   node <TourKit>/run.ts demo/film.ts           records into demo/out/, then copies the film, GIF and
//                                                poster to docs/site/frontdesk-tour.{mp4,gif,jpg}
//
// The brief, scene by scene with what proves each caption, is demo/film.md.
//
// The FrontDesk walkthrough, on synthetic data only. FrontDesk's own tools/serve_tour.py serves
// the exported public demo (inbox, keyboard, Send, which in the demo sends nothing) and a
// throwaway seeded server for the People strip, Ask and Memory; it never reads the real
// ~/.frontdesk, keys or the Keychain, and nothing here calls a model. The last scene is the same
// demo on an iPhone 15 (Chromium's device emulation, real touch input), drawn in a phone frame.
// The film runs in themed sections, each opened by a small section card.
// Every number in a caption is read off the page.

import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { homedir } from "node:os";
import { join } from "node:path";
import type { Locator, Page } from "playwright";
import type { Tour } from "../../TourKit/core/tour.ts";
import type { Storyboard } from "../../TourKit/run.ts";

// TourKit's run.ts sets TOURKIT_HOME before loading a film; its phone helper and Playwright come from there.
const tk = process.env.TOURKIT_HOME;
if (!tk) throw new Error("run this film with TourKit: node <TourKit>/run.ts demo/film.ts");
const { Phone } = await import(join(tk, "core/mobile.ts"));
const { devices } = createRequire(join(tk, "run.ts"))("playwright");

const REPO = process.env.FRONTDESK_REPO ?? join(import.meta.dirname, "..");  // the checkout this film lives in
const IMG = join(REPO, "frontdesk/demo_data/img");
const SITE = join(REPO, "docs/site");
// A worktree has no .venv of its own: use the main checkout's.
const PY = [join(REPO, ".venv/bin/python"), join(homedir(), "Projects/FrontDesk/.venv/bin/python")].find(existsSync)!;
const BG = "#eef0f3";

const text = async (l: Locator) => ((await l.first().textContent()) ?? "").trim();
// A toast has done its job once its caption is read; left alone it lingers for 10 s into the next scene.
const dismissToast = (p: Page) => p.evaluate(() => { const t = document.getElementById("toast"); if (t) t.hidden = true; });
const must = (ok: boolean, why: string) => { if (!ok) throw new Error(`storyboard premise failed: ${why}`); };

async function film(t: Tour, urls: Record<string, string>) {
  const page: Page = t.page;
  const card = (subject: string) => page.locator("main li.card", { has: page.locator(".subject", { hasText: subject }) });
  const row = (c: Locator) => c.locator(":scope > .row");
  const R = { place: "right" as const, maxW: 264 };
  const blur = () => page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());

  await t.goto(urls.static!);
  await page.locator("main li.card").first().waitFor();
  await t.settle(800);

  // The title card hands straight over to the first section card: no glimpse of the inbox between.
  await t.intro("FrontDesk", "An inbox agent that runs on your computer.", 2000, { keep: true });

  // ---- Ranking (static demo)
  await t.chapter("Ranked for you", "Gmail and Slack in one list, grouped into Needs you, FYI and Ignore.");
  const counts = (await page.locator("#counts li").allTextContents()).map((s) => s.trim());
  const n = (label: string) => counts.find((c) => c.endsWith(label))?.split(/\s+/)[0];
  const [need, fyi, ign] = [n("Needs you"), n("FYI"), n("Ignore")];
  must(!!need && !!fyi && !!ign, `counts misread: ${counts.join(" | ")}`);
  const ids = await page.locator("section[aria-label='Needs you'] li.card")
    .evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.id ?? ""));
  must(ids.some((i) => i.startsWith("slack:")) && ids.some((i) => i.startsWith("gmail:")), "Needs you is not mixed Gmail and Slack");
  await t.say(`Gmail and Slack, ranked together: ${need} need you, ${fyi} FYI, ${ign} to ignore.`,
    page.locator("#counts li").first(), { place: "below", maxW: 420 });
  await t.click(card("Decision needed").locator(":scope > .star"), 600);
  const toggle = page.locator("#counts .starview");
  must((await text(toggle)).includes("1 Starred"), `star count misread: ${await text(toggle)}`);
  await t.say("Star a thread and it joins the Starred view.", toggle, { place: "below", maxW: 300 });
  // A real Move to: a reminder ranked Needs you goes to FYI, the header counts follow, then Undo.
  const clean = card("Reminder: cleaning");
  await t.click(row(clean), 650);
  const cpick = clean.locator("select.movepick");
  must((await cpick.inputValue()) === "needs_you", "cleaning reminder is not in Needs you");
  await t.say("Ranked in the wrong place? Move to puts it where it belongs.", cpick, { place: "left", maxW: 300 });
  // The native list can't be filmed: show the pick on the control itself, then let it apply.
  const pb = (await cpick.boundingBox())!;
  await page.evaluate(([x, y]) => (window as any).tourUI.click(x, y), [pb.x + pb.width / 2, pb.y + pb.height / 2] as const);
  await cpick.evaluate((e: HTMLSelectElement) => { e.value = "fyi"; });
  await t.hold(1300);
  await cpick.evaluate((e: HTMLSelectElement) => e.dispatchEvent(new Event("change", { bubbles: true })));
  await t.settle(900);
  // Two captions run longer than the toast's 10 s: keep it (and its Undo) up until it is used.
  await page.evaluate("clearTimeout(toastTimer)");
  must((await clean.locator("xpath=ancestor::section").getAttribute("aria-label")) === "FYI", "the reminder did not move to FYI");
  await t.say("It drops out of Needs you and lands in FYI.", row(clean), { ...R });
  const after = (await page.locator("#counts li").allTextContents()).map((s) => s.trim());
  const m = (label: string) => Number(after.find((c) => c.endsWith(label))?.split(/\s+/)[0]);
  const [need2, fyi2] = [m("Needs you"), m("FYI")];
  must(need2 === Number(need) - 1 && fyi2 === Number(fyi) + 1, `counts after Move to misread: ${after.join(" | ")}`);
  must((await clean.locator("xpath=ancestor::section").getAttribute("aria-label")) === "FYI", "the reminder did not move to FYI");
  await t.say(`Moved to FYI: now ${need2} need you, ${fyi2} FYI. Your call is kept as a private label.`,
    page.locator("#counts li").first(), { place: "below", maxW: 420 });
  const mtoast = page.locator("#toast");
  must((await text(mtoast)).startsWith("Moved to FYI"), `move toast misread: ${await text(mtoast)}`);
  await t.click(mtoast.getByRole("button", { name: "Undo" }), 900);
  must((await clean.locator("xpath=ancestor::section").getAttribute("aria-label")) === "Needs you", "Undo did not move it back");
  await dismissToast(page);
  if ((await row(clean).getAttribute("aria-expanded")) === "true") await row(clean).click();
  // Clicking made the reminder the current thread; the keyboard scene starts from the top.
  await page.evaluate("currentId = null; document.querySelectorAll('main li.card.current').forEach(e => e.classList.remove('current'))");
  await blur();
  await page.evaluate(() => window.scrollTo(0, 0));
  await t.settle(300);

  // ---- Keyboard (bindings from frontdesk/web/app.js onKey)
  await t.chapter("Keyboard shortcuts", "Open, archive, star and move threads without the mouse.");
  await t.press("?", { afterMs: 400 });
  await t.say("Press ? for the shortcuts.", page.locator("#help .helpbox"), { ...R });
  await t.press("Escape", { afterMs: 300 });
  for (const k of ["j", "j", "j", "k"]) await t.press(k, { holdMs: 500, afterMs: 330 });
  const current = page.locator("main li.card.current");
  const curSubject = await text(current.locator(".subject"));
  must(curSubject.startsWith("Signed SOW"), `j/k landed on the wrong thread: ${curSubject}`);
  await t.press("Enter", { afterMs: 750 });
  const off = await t.latency("**/api/items.json", 2200);   // the static demo answers instantly; show the fade
  await t.press("e", { afterMs: 250 });
  const leaving = page.locator("main li.card.leaving");
  must((await leaving.count()) === 1, "e did not start the archive fade");
  await t.say("j and k move, Enter opens, e archives: the row fades, with Undo.", leaving, { ...R });
  await card(curSubject).waitFor({ state: "detached", timeout: 5000 });
  await off();
  const toast = page.locator("#toast");
  must((await text(toast)).startsWith("Archived: Signed SOW"), `archive toast misread: ${await text(toast)}`);
  await t.click(toast.getByRole("button", { name: "Undo" }), 800);
  must((await card(curSubject).count()) === 1, "Undo did not bring the SOW back");
  await dismissToast(page);
  await t.press("k", { holdMs: 500, afterMs: 400 });
  must((await text(current.locator(".subject"))).startsWith("Signed SOW"), "k after Undo missed the SOW");
  await t.press("s", { afterMs: 700 });
  const rowStar = current.locator(":scope > .star");
  must((await rowStar.getAttribute("aria-pressed")) === "true", "s did not star the SOW");
  await t.press("v", { afterMs: 700 });
  const pick = current.locator("select.movepick");
  must(await pick.evaluate((e) => e === document.activeElement), "v did not focus Move to");
  await t.say("s stars it. v opens Move to, for when the ranking put it in the wrong place.", pick, { place: "left", maxW: 300 });
  await blur();

  // ---- Ask (the throwaway seeded server)
  await t.chapter("Some mail needs a decision", "A reply is the easy part. You want advice that knows your history.", {
    under: async () => {
      await t.coveredGoto(urls.live!);
      await page.locator("main li.card").first().waitFor();
    },
  });
  const dec = card("Decision needed");
  await t.click(row(dec), 500);
  await t.click(dec.locator("details.ask > summary"), 700);
  const q = dec.locator(".ask textarea");
  must((await q.inputValue()).trim().length > 20, "Ask box did not start with the starter question");
  await t.say("Ask starts with a question already in the box. Edit it, or just ask.", q, { ...R });
  await t.click(row(dec), 500);   // fold it away
  const cook = card("Cooking afternoon");
  await t.click(row(cook), 500);
  await t.click(cook.locator("details.ask > summary"), 700);
  const answer = cook.locator(".answertext").first();
  must((await text(answer)).includes("An unconfirmed note says"), "recorded Ask answer changed");
  await t.say("Asked whether to just sign the form, it answers: “An unconfirmed note says…”",
    { locator: answer, phrase: "An unconfirmed note says" }, { ...R, around: cook });
  const follow = cook.locator(".ask textarea");
  must((await follow.inputValue()) === "" && (await follow.getAttribute("placeholder")) === "Ask a follow-up",
    "follow-up box is not empty");
  await t.say("After an answer the box is empty, ready for a follow-up.", follow, { ...R });
  await blur();

  // ---- Memory
  await t.chapter("Memory can be wrong", "An assistant that remembers can remember wrong. You need to see who wrote each note.", { under: async () => {
    await row(cook).click();          // fold the cooking thread under the card
    await page.evaluate(() => window.scrollTo(0, 0));
  } });
  const sow = card("Signed SOW");
  await t.click(row(sow), 600);
  const chip = sow.locator(".peoplestrip .personchip").first();
  must((await text(chip)).startsWith("Rafael Duarte"), `SOW chip misread: ${await text(chip)}`);
  await t.click(chip, 600);
  const editor = sow.locator(".personeditor");
  must((await editor.count()) === 1, "chip did not open the note editor");
  must((await text(editor.locator(".authorlabel").last())).startsWith("Written by you"), "editor label misread");
  await t.say("PEOPLE, above the subject: click someone to read or edit your note on them.", editor, { ...R });
  await page.keyboard.press("Escape");
  await t.settle(300);
  await t.press("m", { afterMs: 800 });
  const mem = page.locator("#profilepanel .memorybox");
  const prof = mem.locator(".memsection").first();
  must((await text(prof.locator("h3"))) === "Profile" && (await text(prof.locator(".situationtext"))).length > 20,
    "Memory does not open on the profile");
  await t.say("m opens Memory, kept on this computer. First, your profile: who you are, in your words.",
    prof, { place: "left", maxW: 300 });
  const sit = mem.locator(".situation:not(.people)");
  const items = sit.locator(".situationitem");
  must((await text(items.nth(0).locator(".authorlabel"))).startsWith("Written by you"), "first situation not the owner's");
  must((await text(items.nth(1).locator(".authorlabel"))).endsWith("not confirmed"), "second situation not unconfirmed");
  await t.say("Then What's going on. One line here is unconfirmed.",
    sit, { place: "left", maxW: 264 });
  const people = mem.locator(".situation.people .situationitem");
  const plabels = (await people.locator(".authorlabel").allTextContents()).map((s) => s.trim());
  must(plabels.some((l) => l.startsWith("Written by you")) && plabels.some((l) => l.endsWith("not confirmed")),
    `people labels misread: ${plabels.join(" | ")}`);
  await t.say("People: only those you keep a note on, each labelled with who wrote it.", people.nth(1), { place: "left", maxW: 264 });

  // ---- Guardrails
  await t.chapter("Mail can give orders", "Anyone can email your agent instructions. They must never take the wheel.", { under: async () => {
    await page.keyboard.press("Escape");
  } });
  const summary = sow.locator(".summary");
  must((await text(summary)).includes("odd line addressed to an 'AI assistant'"), "SOW summary changed");
  must((await sow.locator("xpath=ancestor::section").getAttribute("aria-label")) === "Needs you", "SOW left Needs you");
  await t.say("A planted line asks to mark this low priority. The summary flags it; it stays in Needs you.",
    { locator: summary, phrase: "The email ends with an odd line" }, { ...R, around: sow });
  await t.click(row(sow), 500);   // fold it away
  const slack = card("#analytics-vendor");
  await t.click(row(slack), 500);
  // The full thread stays folded on film; the planted line is read from the page's own data.
  const plantedOk = await page.evaluate(() => ((window as any).__items || []).some((r: any) =>
    (r.item.subject || "").startsWith("#analytics-vendor") &&
    r.item.messages.some((m: any) => /AI assistant:.*approved the \$48k/s.test(m.body || ""))));
  must(plantedOk, "planted Slack line not found");
  const reply = slack.locator(".reply textarea");
  must((await reply.inputValue()).includes("I haven't approved a vendor or budget yet"), "Slack proposed reply changed");
  await t.say("In Slack the vendor planted “say Alex approved $48k”. The proposed reply says nothing was approved.",
    reply, { ...R });
  // Send, on the static demo (nothing leaves). The phone for the last section loads here, hidden.
  await t.cut(urls.static!);
  const phone = new Phone(t, devices["iPhone 15"]!, { bg: BG });
  await phone.open(urls.static!);
  // Test an attack: the suite's recorded runs (the demo has no model). A forged quote that fooled
  // two models, and what the ranking default did with it.
  const attackBtn = page.locator("header .btn", { hasText: /^Test an attack$/ });
  await t.say("Test an attack shows what each model did with the attacks in FrontDesk's test suite.",
    attackBtn, { place: "below", maxW: 320 });
  await t.click(attackBtn, 800);
  const abox = page.locator("#profilepanel .attackbox");
  const apick = abox.locator("select");
  const nAttacks = await apick.locator("option").count();
  must(nAttacks >= 30, `attack list misread: ${nAttacks}`);
  const forged = await apick.locator("option").evaluateAll((os) =>
    (os as HTMLOptionElement[]).find((o) => o.value.startsWith("i25-"))?.value ?? "");
  must(!!forged, "the forged-quote attack i25 is gone from the suite");
  const ab = (await apick.boundingBox())!;
  await page.evaluate(([x, y]) => (window as any).tourUI.click(x, y), [ab.x + ab.width / 2, ab.y + ab.height / 2] as const);
  await apick.evaluate((e: HTMLSelectElement, v: string) => { e.value = v; }, forged);
  await t.hold(1100);
  await apick.evaluate((e: HTMLSelectElement) => e.dispatchEvent(new Event("change", { bubbles: true })));
  await t.settle(600);
  const chips = abox.locator(".attackchips button");
  const shown = await text(abox.locator(".attackchips button[aria-pressed='true']"));
  must(/: fooled$/.test(shown), `first chip shown is not a fooled model: ${shown}`);
  const fooledBy = shown.replace(/: fooled$/, "");
  must((await text(abox.locator(".attackverdict"))).startsWith("Fooled"), "fooled verdict not shown");
  await t.say(`One of the ${nAttacks} attacks: a forged quote. It fooled ${fooledBy}.`,
    abox.locator(".attackverdict"), { place: "left", maxW: 320 });
  const argon = chips.filter({ hasText: /^Gemini 4 Argon: / });
  must((await text(argon)) === "Gemini 4 Argon: resisted", `Argon chip misread: ${await text(argon)}`);
  await t.click(argon, 700);
  must((await text(abox.locator(".attackverdict"))).startsWith("Resisted"), "Argon's verdict is not Resisted");
  await t.say("Gemini 4 Argon, the model that ranks your inbox, resisted it.", abox.locator(".attackverdict"),
    { place: "left", maxW: 320 });
  await t.click(abox.getByRole("button", { name: "Close" }), 500);
  const sow2 = card("Signed SOW");
  await t.click(row(sow2), 550);
  const ta = sow2.locator(".reply textarea");
  must((await ta.inputValue()).includes("[date]"), "SOW reply has no [date] placeholder");
  await t.click(ta, 200);
  await ta.evaluate((e: HTMLTextAreaElement) => { const i = e.value.indexOf("[date]"); e.setSelectionRange(i, i + 6); });
  await t.hold(300);
  await t.type("Tuesday");
  await t.click(sow2.locator(".reply .btn.send"), 550);
  const meta = page.locator("#profilepanel dl.sendmeta");
  const to = await text(meta.locator("dd").first());
  must(/@/.test(to), `recipient misread: ${to}`);
  await t.say(`You fill in [date]. Send shows exactly who gets it: ${to}.`, meta, { place: "left", maxW: 440 });
  await t.click(page.locator("#profilepanel .btn.primary", { hasText: /^Send$/ }), 550);
  must((await text(toast)).startsWith("Demo: sending in"), "undo toast not shown");
  await t.say("Thirty seconds to undo. In the demo, nothing is sent.", toast, { place: "above" });

  // ---- Web images: the demo newsletter's banner and open pixel, served here from the repo's copy.
  // TourKit records with bypassCSP (its overlay needs it), which would also lift the message
  // page's img-src rule; the route enforces that rule instead: images only for a -images page.
  await page.route("https://frontdesk.ocarlsen.com/img/**", (route) => {
    if (!/-images\.html$/.test(route.request().frame().url())) return route.abort("blockedbyclient");
    const name = new URL(route.request().url()).pathname.split("/").pop()!;
    return route.fulfill({ body: readFileSync(join(IMG, name)), contentType: name.endsWith(".svg") ? "image/svg+xml" : "image/gif" });
  });
  const news = card("The Weekly Diff");
  await t.chapter("Mail can watch you", "A tiny image in an email tells the sender you opened it.", { under: async () => {
    // The send countdown re-shows its toast every second: undo it (unseen, under the card).
    await toast.getByRole("button", { name: "Undo" }).click();
    await t.settle(300);
    await dismissToast(page);
    await row(sow2).click();           // fold the SOW under the card
    await page.locator("main section summary", { hasText: /^Ignore \(\d+\)$/ }).click();   // Ignore starts collapsed
    await news.scrollIntoViewIfNeeded();
  } });
  await t.click(row(news), 600);
  const full = news.locator("details.fullthread");
  if (!(await full.evaluate((d) => (d as HTMLDetailsElement).open))) await t.click(full.locator("summary"), 700);
  const ibar = news.locator(".imagebar");
  await ibar.waitFor();
  must((await text(ibar)).startsWith("Images are hidden."), `image bar misread: ${await text(ibar)}`);
  const frame = news.locator("iframe.mailframe").first();
  const banner = page.frameLocator(`li.card[data-id="${await news.getAttribute("data-id")}"] iframe.mailframe`).locator("img").first();
  must((await banner.evaluate((i) => (i as HTMLImageElement).naturalWidth)) === 0, "the banner loaded before Show images");
  await t.say("Images stay off until you ask, so the sender learns nothing.", ibar, { place: "above", maxW: 360 });
  await t.click(ibar.getByRole("button", { name: "Show images" }), 900);
  must(/-images\.html$/.test((await frame.getAttribute("src")) ?? ""), "Show images did not reload with images");
  await t.settle(400);
  must((await banner.evaluate((i) => (i as HTMLImageElement).naturalWidth)) > 0, "the banner did not load after Show images");
  await t.say("Show images loads them for this message. Always show remembers the sender.", frame, { ...R });

  // ---- On your phone: the same demo, real touch input
  try {
    const mp = phone.page;
    const mcard = (subject: string) => mp.locator("main li.card", { has: mp.locator(".subject", { hasText: subject }) });
    await mcard("Signed SOW").waitFor();
    await t.chapter("Away from your desk", "Triage shouldn't wait for a laptop.", { under: () => phone.show(0) });
    const P = { place: "right" as const, maxW: 300, around: phone.frame };
    const m = mcard("Signed SOW");
    const b = await phone.box(m.locator(":scope > .row"));
    const from = { x: b.x + b.width * 0.8, y: b.y + b.height / 2 };
    await phone.drag(from, { x: from.x - 70, y: from.y + 2 }, 650, { hold: true });
    must(await m.evaluate((li) => li.classList.contains("swiping")), "the row did not follow the finger");
    must((await text(m.locator(".swipe-reveal"))) === "Archive", "swipe does not reveal Archive");
    await t.say("Swipe left: Archive shows under the row.", await phone.proxy(m), { ...P });
    await phone.drag({ x: from.x - 70, y: from.y + 2 }, { x: from.x - 230, y: from.y + 4 }, 500);
    await m.waitFor({ state: "detached", timeout: 5000 });
    await t.settle(500);
    const mt = mp.locator("#toast");
    must((await text(mt)).startsWith("Archived: Signed SOW"), `phone toast misread: ${await text(mt)}`);
    const tb = await phone.box(mt);
    must(tb.width > 300 && tb.height < 80, `phone toast is squeezed: ${Math.round(tb.width)}x${Math.round(tb.height)}`);
    await t.say("Archived, with Undo.", await phone.proxy(mt), { ...P });
    await dismissToast(mp);
    const d = mcard("Decision needed");
    const star = d.locator(":scope > .star");
    await phone.tap(star, 900);
    must((await star.getAttribute("aria-pressed")) === "true", "tap did not star the thread");
    await t.say("Tap the star to keep a thread for later.", await phone.proxy(star), { ...P });
  } finally {
    await phone.close();
  }

  await t.outro("FrontDesk", "Open source: github.com/ocarlsen/frontdesk", 2400);
}

const storyboard: Storyboard = {
  name: "frontdesk",
  // FrontDesk's light tokens (frontdesk/web/app.css :root)
  // Caption and card subtitle sizes as in the session-notes film (21px, 38px); the bubbles keep their widths.
  theme: { text: "#1c2026", accent: "#2f5fd0", bg: BG, muted: "#5f6873", line: "#dde1e6", card: "#ffffff",
           captionPx: 21, captionWidth: 380, cardSubPx: 38 },
  viewport: { width: 1440, height: 900 },
  band: 112,
  async start() {
    const p = spawn(PY, [join(REPO, "tools/serve_tour.py")], { stdio: ["pipe", "pipe", "inherit"] });
    const urls = await new Promise<Record<string, string>>((ok, fail) => {
      let buf = "";
      p.stdout!.on("data", (c: Buffer) => { buf += c; if (buf.includes("\n")) ok(JSON.parse(buf.split("\n")[0]!)); });
      p.on("exit", (code) => fail(new Error(`serve_tour.py exited ${code}`)));
    });
    return {
      urls,
      stop: () => new Promise<void>((ok) => { p.on("exit", () => ok()); p.stdin!.end(); }),
    };
  },
  run: film,
  gif: { from: 0, seconds: 20, width: 800, fps: 10 },
  posterAt: 1,
  outputs: {
    mp4: join(SITE, "frontdesk-tour.mp4"),
    gif: join(SITE, "frontdesk-tour.gif"),
    poster: join(SITE, "frontdesk-tour.jpg"),
  },
};

export default storyboard;
