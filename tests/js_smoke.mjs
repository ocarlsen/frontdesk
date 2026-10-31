// Runs app.js against a tiny stub DOM and builds a card and its detail view, so a runtime error
// in the page (not just a syntax error) fails the test suite. Usage: node tests/js_smoke.mjs [path/to/app.js]
import { readFileSync } from "node:fs";
import vm from "node:vm";

class Node {
  constructor(tag) {
    this.tagName = (tag || "").toUpperCase(); this.children = []; this.attrs = {};
    this.dataset = {}; this.listeners = {}; this.textContent = "";
    this.style = { props: {}, setProperty(k, v) { this.props[k] = v; }, removeProperty(k) { delete this.props[k]; } };
    const cl = new Set();
    this.classList = { add: (...c) => c.forEach(x => cl.add(x)), remove: (...c) => c.forEach(x => cl.delete(x)),
                       toggle: (c, on) => { if (on === undefined ? !cl.has(c) : on) cl.add(c); else cl.delete(c); },
                       contains: c => cl.has(c) || (this.className || "").split(" ").includes(c) };
    this.hidden = false; this.value = ""; this.disabled = false;
  }
  get childNodes() { return this.children; }
  append(...c) { this.children.push(...c); }
  prepend(...c) { this.children.unshift(...c); }
  replaceChildren(...c) { this.children = c; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  scrollIntoView() {}
  focus() {}
}
const document = {
  documentElement: new Node("html"),
  createElement: t => new Node(t),
  createTextNode: t => ({ textContent: t }),
  getElementById: () => new Node("div"),
  querySelectorAll: () => [],
  addEventListener() {},
};
// Timers never keep the process alive (a toast hides itself after 10 s).
const quietTimeout = (f, ms) => { const t = setTimeout(f, ms); if (t.unref) t.unref(); return t; };
const ctx = { document, window: {}, console, setTimeout: quietTimeout, clearTimeout, crypto: globalThis.crypto,
              navigator: {}, fetch: async () => ({ ok: true, json: async () => [] }),
              Date, Math, JSON, Promise, Set, Map, WeakMap, Number, String, Array, Object };
vm.createContext(ctx);
const src = process.argv[2] || new URL("../frontdesk/web/app.js", import.meta.url);
vm.runInContext(readFileSync(src, "utf8"), ctx);

const item = { id: "gmail:t1", subject: "Lunch", url: "https://mail.google.com/mail/#all/t1",
  updated_at: "2026-10-28T16:00:00Z",
  messages: [{ sender: "Ann <ann@example.com>", sent_at: "2026-10-28T16:00:00Z", body: "Lunch?",
               is_mine: false, has_html: false }] };
const triage = { bucket: "needs_you", urgency: 4, reason: "Ann asks", proposed_reply: "Yes.",
  summary: "Ann asks about lunch.", model: "x", triaged_at: "2026-10-28T16:00:00Z",
  prompt_version: "v", model_served: "x", tokens_in: 1, tokens_out: 1, cache_read: 0,
  latency_ms: 1, cost_usd: 0.001, model_bucket: "" };
vm.runInContext("buildCard", ctx)(item, triage);
vm.runInContext("buildDetail", ctx)(item, triage);
vm.runInContext("buildDetail", ctx)(item, { ...triage, summary: "", proposed_reply: "" });
vm.runInContext("buildDetail", ctx)(item, null);
// Memory: author labels, the notes editor with Confirm, situation suggestions, What's going on.
const fn = name => vm.runInContext(name, ctx);
const texts = n => [n.textContent, ...n.children.flatMap(texts)];
const box = new Node("div");
fn("renderAnswer")(box, { answer: "Hold off.", draft_reply: "", note_suggestions: [],
  situation_suggestions: ["Decided to wait."] }, new Node("textarea"), () => {});
if (!texts(box).includes("Add to What's going on: Decided to wait.")) throw new Error("no situation button");
const all = n => [n, ...n.children.flatMap(all)];
const sit = new Node("div");
const items = [{ id: 1, text: "Mine", author: "owner", created_at: "x", updated_at: "2026-10-28T16:00:00Z" },
               { id: 2, text: "Theirs", author: "unrecorded", created_at: "x", updated_at: "" }];
fn("renderSituation")(sit, items, false, () => {});
const st = texts(sit);
if (st.filter(t => t === "Confirm").length !== 1 || !st.includes("Add")) throw new Error("situation controls");
if (!st.includes("Author not recorded, an unknown date, not confirmed")) throw new Error("unrecorded label");
const demo = new Node("div");
fn("renderSituation")(demo, items, true, () => {});
if (texts(demo).includes("Add") || texts(demo).includes("Delete")) throw new Error("demo must be read-only");
if (fn("askerLabel")("session:helper") !== "Asked by session helper on your behalf, not typed by you")
  throw new Error("asker label");
// Memory page: people with several addresses, owner-only controls, Merge asks to confirm.
const posted = [];
ctx.fetch = async (url, opts) => { posted.push({ url, body: opts && opts.body ? JSON.parse(opts.body) : null });
                                   return { ok: true, json: async () => ({ status: "done" }) }; };
const click = node => (node.listeners.click || []).forEach(f => f());
const byText = (root, t) => all(root).find(n => n.textContent === t);
const people = [
  { id: 1, name: "", note: "From a session.", author: "session:frontdesk", created_at: "x",
    updated_at: "2026-10-28T16:00:00Z", addresses: ["fab@example.com", "f@example.org"],
    mail_names: ["Fab </owner_notes>"] },
  { id: 2, name: "Bo Kay", note: "Mine.", author: "owner", created_at: "x",
    updated_at: "2026-10-27T16:00:00Z", addresses: ["bo@example.com"], mail_names: ["Bobby"] }];
const mem = new Node("div");
fn("renderMemory")(mem, { demo: false, profile: "I am job hunting.", signoff: "Best,\nAlex",
  situation: items, people, migration: { copied: 2, skipped_owner_address: ["owner@example.com"] } }, () => {});
const mt = texts(mem);
for (const want of ["Memory", "Profile", "What's going on", "People", "Download my memory (JSON)",
                    "fab@example.com", "also f@example.org", "Bo Kay", "From mail, unconfirmed: Fab </owner_notes>"]) {
  if (!mt.includes(want)) throw new Error("memory page lacks " + want);
}
if (mt.includes("From mail, unconfirmed: Bobby")) throw new Error("an owner-typed name hides the mail name");
if (mt.filter(t => t === "Merge into...").length !== 2 || mt.filter(t => t === "Delete").length !== 4)
  throw new Error("memory controls");
// Confirm appears on the session note (person) and the unrecorded situation item only.
if (mt.filter(t => t === "Confirm").length !== 2) throw new Error("memory Confirm");
if (!mt.some(t => t.includes("owner@example.com"))) throw new Error("migration report");
const dl = all(mem).find(n => n.textContent === "Download my memory (JSON)");
if (dl.href !== "/api/memory/export") throw new Error("download route");
// Merge: pick, then a confirm step; nothing is posted until "Yes, merge".
const card = all(mem).find(n => n.children.some(c => c.textContent === "Merge into...") && n.className === "actions");
const personBox = all(mem).find(n => n.className === "situationitem person" && n.children.includes(card));
click(byText(personBox, "Merge into..."));
const pick = all(personBox).find(n => n.tagName === "SELECT");
pick.value = "2";
click(byText(personBox, "Merge"));
if (!texts(personBox).some(t => t.endsWith("This cannot be undone."))) throw new Error("no merge confirm step");
if (posted.length) throw new Error("merge posted before confirming");
click(byText(personBox, "Yes, merge"));
await new Promise(r => setTimeout(r, 0));
if (posted.length !== 1 || posted[0].body.kind !== "person_merge" || posted[0].body.id !== 1 ||
    posted[0].body.into !== 2 || posted[0].body.author !== "owner") throw new Error("merge request");
// The demo's Memory page is empty and read-only.
const dmem = new Node("div");
fn("renderMemory")(dmem, { demo: true, profile: "", signoff: "", situation: [], people: [], migration: null }, () => {});
const dt = texts(dmem);
for (const no of ["Download my memory (JSON)", "Edit", "Delete", "Merge into...", "Add", "Confirm"]) {
  if (dt.includes(no)) throw new Error("demo memory must be read-only: " + no);
}
if (!dt.some(t => t.startsWith("Demo: nothing is remembered here"))) throw new Error("demo empty text");
posted.length = 0;
// A note suggestion goes to the thread-bound action with the thread's id.
const sug = new Node("div");
fn("renderAnswer")(sug, { answer: "x", draft_reply: "", situation_suggestions: [],
  note_suggestions: [{ who: "fab@example.com", text: "Wants a demo." }] }, new Node("textarea"), () => {}, "gmail:t1");
click(byText(sug, "Save note for fab@example.com: Wants a demo."));
await new Promise(r => setTimeout(r, 0));
if (posted.length !== 1 || posted[0].body.kind !== "note_suggestion" || posted[0].body.item_id !== "gmail:t1")
  throw new Error("suggestion request");
// Slack people are keyed by user id; the page shows display names, never a raw key.
const SK = "slack:t0:u0ann";
const noKey = root => { const bad = texts(root).filter(t => typeof t === "string" && t.includes("slack:"));
                        if (bad.length) throw new Error("raw Slack key shown: " + bad[0]); };
const smem = new Node("div");
const slackPeople = [
  { id: 7, name: "", note: "Linked.", author: "owner", created_at: "x", updated_at: "2026-10-28T16:00:00Z",
    addresses: [SK, "ann lee"], mail_names: [],
    address_labels: { [SK]: { text: "Ann Lee", kind: "slack" }, "ann lee": { text: "ann lee", kind: "slack_name" } } },
  { id: 8, name: "Sam K", note: "Unlinked.", author: "owner", created_at: "x", updated_at: "2026-10-27T16:00:00Z",
    addresses: ["sam"], mail_names: [], address_labels: { sam: { text: "sam", kind: "slack_unlinked" } } },
  { id: 9, name: "Bo", note: "Two places.", author: "owner", created_at: "x", updated_at: "2026-10-26T16:00:00Z",
    addresses: ["bo@example.com", "slack:t0:u0bo"], mail_names: [],
    address_labels: { "slack:t0:u0bo": { text: "Bo Diaz", kind: "slack" } } }];
fn("renderMemory")(smem, { demo: false, profile: "", signoff: "", situation: [], people: slackPeople, migration: null }, () => {});
const smt = texts(smem);
for (const want of ["Ann Lee (Slack)", "also ann lee (old Slack name)", "sam (Slack name, not linked to a user)",
                    "bo@example.com", ", Bo Diaz (Slack)"]) {
  if (!smt.includes(want)) throw new Error("slack memory lacks " + want);
}
if (all(smem).find(n => n.textContent === "Ann Lee (Slack)").title !== SK) throw new Error("key in the title");
if (all(smem).find(n => n.textContent === ", Bo Diaz (Slack)").title !== "slack:t0:u0bo") throw new Error("span title");
noKey(smem);
// Edit shows every address and the editor (the address line must exist in the edit view).
const annBox = all(smem).find(n => n.className === "situationitem person" && texts(n).includes("Linked."));
click(byText(annBox, "Edit"));
if (!all(annBox).some(n => n.tagName === "TEXTAREA") || !texts(annBox).includes(", ann lee (old Slack name)"))
  throw new Error("edit view");
noKey(annBox);
const slab = new Node("div");
fn("renderAnswer")(slab, { answer: "x", draft_reply: "", situation_suggestions: [],
  note_suggestions: [{ who: SK, text: "Ships Friday.", label: "Ann Lee" }] }, new Node("textarea"), () => {}, "slack:C1:1.0");
if (!texts(slab).includes("Save note for Ann Lee: Ships Friday.")) throw new Error("suggestion label");
noKey(slab);
// The demo's Slack threads live in a made-up workspace (examplecorp.example.com): no Open in
// Slack link, no Save draft, and the static demo's Send names the Slack target, sending nothing.
const demoSlack = { id: "slack:C01PLATFRM:1793200800.000900", source: "slack", subject: "#platform: review?",
  url: "https://examplecorp.example.com/archives/C01PLATFRM/p1793200800000900?thread_ts=1793200800.000900",
  updated_at: "2026-10-28T16:00:00Z", labels: ["slack", "channel"],
  messages: [{ sender: "Ines", sent_at: "2026-10-28T16:00:00Z", body: "review?", is_mine: false, has_html: false }] };
const sd = vm.runInContext("buildDetail", ctx)(demoSlack, triage);
if (all(sd).some(n => n.tagName === "A" && n.textContent === "Open in Slack")) throw new Error("demo links Slack");
if (texts(sd).includes("Save draft")) throw new Error("Slack thread offers a Gmail draft");
const real = vm.runInContext("buildDetail", ctx)({ ...demoSlack, url: "https://acme.slack.com/archives/C1/p1" }, triage);
if (!all(real).some(n => n.tagName === "A" && n.textContent === "Open in Slack")) throw new Error("real Slack link lost");
// ---- The reply action row: a reply group (Save, Send, Copy) and a thread group (Move to, Star,
// Archive or Done, then the Open link, which is a link, not a .btn).
const sameRow = (a, b, m) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(m + ": " + JSON.stringify(a)); };
const rowGroups = det => {
  const row = all(det).find(n => n.className === "actions replyactions");
  if (!row) throw new Error("no reply action row");
  const g = cls => row.children.find(n => n.className === cls);
  const label = n => n.tagName === "LABEL" ? "moveto" : n.tagName === "A" ? "link:" + n.textContent
    : (n.className || "").split(" ").includes("btn-icon") ? "icon:" + n.attrs["aria-label"] : n.textContent;
  return { row, reply: (g("replygroup")?.children || []).map(label), thread: (g("threadgroup")?.children || []).map(label),
           threadNodes: g("threadgroup")?.children || [] };
};
const gd = rowGroups(fn("buildDetail")(item, triage));
sameRow(gd.row.children.map(n => n.className), ["replygroup", "threadgroup"], "row holds the two groups");
sameRow(gd.reply, ["Save as Gmail draft", "Send...", "Copy"], "Gmail reply group");
sameRow(gd.thread, ["moveto", "\u2606 Star", "icon:Mark unread (Shift+U)", "Archive", "link:Open in Gmail"], "Gmail thread group");
const gLink = gd.threadNodes.at(-1);
if (gLink.className !== "openlink" || (gLink.className || "").split(" ").includes("btn")) throw new Error("Open in Gmail must be a link, not a .btn");
const gPick = all(gd.row).find(n => n.tagName === "SELECT");
if (!gPick || gPick.className !== "movepick") throw new Error("Move to select must be movepick without modelpick: " + gPick?.className);
const sl = rowGroups(fn("buildDetail")({ ...demoSlack, url: "https://acme.slack.com/archives/C1/p1" }, triage));
sameRow(sl.reply, ["Send...", "Copy"], "Slack reply group");
sameRow(sl.thread, ["moveto", "\u2606 Star", "icon:Mark unread (Shift+U)", "Done", "link:Open in Slack"], "Slack thread group");
const staticRoot = new Node("html");
staticRoot.dataset = { static: "1" };
const sctx = { document: { ...document, documentElement: staticRoot }, window: { __items: [{ item: demoSlack }] },
               console, setTimeout: quietTimeout, clearTimeout, crypto: globalThis.crypto, navigator: {},
               fetch: async () => { throw new Error("static demo fetched"); },
               Date, Math, JSON, Promise, Set, Map, WeakMap, Number, String, Array, Object };
vm.createContext(sctx);
vm.runInContext(readFileSync(src, "utf8"), sctx);
const prep = await vm.runInContext("postAction", sctx)("send_prepare", demoSlack.id, { body: "On it." });
if (!prep.demo || prep.to.join() !== "#platform (thread)") throw new Error("static Slack send: " + JSON.stringify(prep));
// ---- Ask: the box starts with the server's built-in question, editable; one Ask sends the box.
const ADV = "SERVER-ADVISE-SENTINEL: what should I do?";
const askPosts = [];
ctx.fetch = async (url, opts) => {
  if (String(url).startsWith("/api/ask?")) return { ok: true, json: async () => ({ advise: ADV, history: [], notes: {}, people: [] }) };
  if (url === "/api/models") return { ok: true, json: async () => [{ index: 0, label: "M0" }, { index: 1, label: "M1" }] };
  askPosts.push(JSON.parse(opts.body));
  return { ok: true, json: async () => ({ answer: "Go.", draft_reply: "", note_suggestions: [], situation_suggestions: [] }) };
};
const askBody = new Node("div");
await fn("buildAsk")(item, new Node("textarea"), askBody, new Node("summary"));
const askBox = all(askBody).find(n => n.tagName === "TEXTAREA");
if (askBox.value !== ADV) throw new Error("Ask box not pre-filled with the server's question: " + askBox.value);
if (askBox.placeholder) throw new Error("the question is text, not a placeholder");
const askTexts = texts(askBody);
for (const gone of ["Advise me", "Ask all"]) if (askTexts.includes(gone)) throw new Error("still offers " + gone);
for (const kept of ["Ask", "Second opinion", "Polish draft"]) if (!askTexts.includes(kept)) throw new Error("lost " + kept);
if (!all(askBody).some(n => n.tagName === "SELECT")) throw new Error("model picker lost");
const askButtons = all(askBody).filter(n => n.tagName === "BUTTON" && n.textContent === "Ask");
if (askButtons.length !== 1) throw new Error("exactly one Ask button");
askBox.value = "Should I take the 3pm slot?";
click(askButtons[0]);
await new Promise(r => setTimeout(r, 0));
if (askPosts.length !== 1 || askPosts[0].kind !== "ask" || askPosts[0].question !== "Should I take the 3pm slot?" ||
    askPosts[0].mode !== "ask") throw new Error("Ask must send the box text: " + JSON.stringify(askPosts));
if (askBox.value !== "" || askBox.placeholder !== "Ask a follow-up")
  throw new Error("after an answer the box must empty for a follow-up, not repeat the question");
const starterLink = all(askBody).find(n => n.tagName === "BUTTON" && n.textContent === "Use the starter question");
if (!starterLink || starterLink.hidden) throw new Error("the starter-question link must appear after an answer");
click(starterLink);
if (askBox.value !== ADV) throw new Error("the link must put the starter question back");
click(askButtons[0]);                       // restored starter: sends the built-in question as text
await new Promise(r => setTimeout(r, 0));
if (askPosts.length !== 2 || askPosts[1].question !== ADV) throw new Error("the starter question sends as text");
askBox.value = "   ";
click(askButtons[0]);
await new Promise(r => setTimeout(r, 0));
if (askPosts.length !== 2) throw new Error("an empty box must not post");
const second = all(askBody).find(n => n.tagName === "BUTTON" && n.textContent === "Second opinion");
click(second);
await new Promise(r => setTimeout(r, 0));
if (askPosts[2].mode !== "second" || askPosts[2].model !== undefined) throw new Error("the picker applies to Ask only");

// ---- Swipe: pure decision. No action under the lock distance; the axis locks on the first
// clear move; a vertical lock never swipes; only a left move past the threshold acts.
const sw = fn("swipeDecide");
const eq = (a, b, m) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(m + ": " + JSON.stringify(a)); };
eq(sw(-6, 3, null, 390), { lock: null, offset: 0, act: false }, "below the lock distance");
eq(sw(-40, 6, null, 390), { lock: "x", offset: -40, act: false }, "short left swipe");
eq(sw(-160, 8, null, 390), { lock: "x", offset: -160, act: true }, "past the threshold");
eq(sw(-150, 8, "x", 390), { lock: "x", offset: -150, act: false }, "just short of 40% of 390");
eq(sw(60, 2, null, 390), { lock: "x", offset: 0, act: false }, "right swipe does nothing");
eq(sw(-8, 40, null, 390), { lock: "y", offset: 0, act: false }, "vertical scroll");
eq(sw(-300, 20, "y", 390), { lock: "y", offset: 0, act: false }, "a vertical lock stays vertical");
eq(sw(-80, 0, "x", 0), { lock: "x", offset: -80, act: true }, "floor threshold of 72 px");
if (fn("swipeThreshold")(1000) !== 160) throw new Error("threshold cap");
// A mouse never starts a swipe; a touch drag that locks vertical leaves the row alone.
const swCard = fn("buildCard")({ ...item, id: "gmail:sw" }, triage);
const swRow = swCard.children.find(n => n.className === "row");
const fire = (n, t, e) => (n.listeners[t] || []).forEach(f => f(e));
fire(swRow, "pointerdown", { pointerType: "mouse", clientX: 300, clientY: 10, pointerId: 1 });
fire(swRow, "pointermove", { pointerType: "mouse", clientX: 50, clientY: 12, pointerId: 1 });
if ("--swipe" in swCard.style.props || swCard.children.some(n => n.className === "swipe-reveal")) throw new Error("mouse swiped");
fire(swRow, "pointerdown", { pointerType: "touch", clientX: 300, clientY: 10, pointerId: 2 });
fire(swRow, "pointermove", { pointerType: "touch", clientX: 296, clientY: 60, pointerId: 2 });
fire(swRow, "pointermove", { pointerType: "touch", clientX: 100, clientY: 70, pointerId: 2 });
if ("--swipe" in swCard.style.props || swCard.children.some(n => n.className === "swipe-reveal")) throw new Error("vertical drag swiped");
// A horizontal touch drag past the threshold reveals Archive and archives on release.
const swPosts = [];
ctx.fetch = async (url, opts) => { if (url === "/api/action") swPosts.push(JSON.parse(opts.body));
                                   return { ok: true, json: async () => (url === "/api/action" ? { status: "done" } : []) }; };
fire(swRow, "pointerdown", { pointerType: "touch", clientX: 300, clientY: 10, pointerId: 3 });
fire(swRow, "pointermove", { pointerType: "touch", clientX: 280, clientY: 11, pointerId: 3 });
fire(swRow, "pointermove", { pointerType: "touch", clientX: 120, clientY: 14, pointerId: 3 });
const reveal = swCard.children.find(n => n.className === "swipe-reveal");
if (!reveal || reveal.textContent !== "Archive" || swCard.style.props["--swipe"] !== "-180px") throw new Error("swipe reveal");
fire(swRow, "pointerup", { pointerType: "touch", pointerId: 3 });
await new Promise(r => setTimeout(r, 0));
if (swPosts.length !== 1 || swPosts[0].kind !== "archive" || swPosts[0].item_id !== "gmail:sw") throw new Error("swipe archive: " + JSON.stringify(swPosts));
if (!swCard.dataset.swiped) throw new Error("the tap that ends a swipe must not open the thread");

// ---- Star: row and detail toggles; the new state shows at once, pending, and reverts when the
// server refuses (no silent optimistic failure).
const starPosts = [];
let starOk = false;
ctx.fetch = async (url, opts) => {
  if (url === "/api/action") { starPosts.push(JSON.parse(opts.body));
    return starOk ? { ok: true, json: async () => ({ status: "done" }) }
                  : { ok: false, status: 412, json: async () => ({ error: "run frontdesk authorize-actions" }) }; }
  return { ok: true, json: async () => [] };
};
const stItem = { ...item, id: "gmail:st", starred: false, labels: ["INBOX"] };
const stCard = fn("buildCard")(stItem, triage);
const rowStar = stCard.children.find(n => n.className === "star");
if (!rowStar || rowStar.getAttribute("aria-pressed") !== "false") throw new Error("no row star");
const stDetail = fn("buildDetail")(stItem, triage);
const detStar = all(stDetail).find(n => n.className === "btn btn-star");
if (!detStar || detStar.textContent !== "☆ Star") throw new Error("no detail star");
click(rowStar);
if (rowStar.getAttribute("aria-pressed") !== "true" || !rowStar.disabled || !rowStar.classList.contains("pending") ||
    detStar.getAttribute("aria-pressed") !== "true") throw new Error("star must show pending at once on both toggles");
await new Promise(r => setTimeout(r, 0));
if (rowStar.getAttribute("aria-pressed") !== "false" || rowStar.disabled || stItem.starred) throw new Error("refused star must revert");
if (starPosts.length !== 1 || starPosts[0].kind !== "star" || starPosts[0].item_id !== "gmail:st") throw new Error("star request");
starOk = true;
click(rowStar);
await new Promise(r => setTimeout(r, 0));
if (!stItem.starred || starPosts[1].kind !== "star") throw new Error("confirmed star");
const slStar = fn("buildCard")({ ...demoSlack, starred: false }, triage).children.find(n => n.className === "star");
if (!slStar.title.startsWith("Starred in FrontDesk only")) throw new Error("Slack star tooltip");
// Static demo: starring changes this tab only and fetches nothing.
const sstar = await vm.runInContext("postAction", sctx)("star", demoSlack.id);
if (!sstar.demo || !sstar.starred) throw new Error("static star");
// ---- People strip: a chip per person between the subject and the summary; a chip opens that
// person's note right under it, one at a time. Same data as Ask (GET /api/ask).
const tick = () => new Promise(r => setTimeout(r, 0));
const stripPosts = [];
let stripData = null;
ctx.fetch = async (url, opts) => {
  if (String(url).startsWith("/api/ask?")) return { ok: true, json: async () => stripData() };
  if (url === "/api/action") { stripPosts.push(JSON.parse(opts.body)); return { ok: true, json: async () => ({ status: "done" }) }; }
  return { ok: true, json: async () => [] };
};
const stripOf = root => all(root).find(n => n.className === "peoplestrip");
const chipTexts = root => all(stripOf(root)).filter(n => (n.className || "").includes("personchip")).map(n => n.textContent);
const editors = root => all(root).filter(n => n.className === "personeditor");
const openStrip = async (data, tri = triage, it = item) => {
  stripData = () => data;
  const d = fn("buildDetail")(it, tri);
  await tick(); await tick();
  return d;
};
const NOW = "2026-10-28T16:00:00Z";
let d = await openStrip({ people: ["fab@example.com", "bo@example.com", "cy@example.com"], notes: {
  "fab@example.com": { text: "a", author: "owner", updated_at: NOW },
  "bo@example.com": { text: "b", author: "session:frontdesk", updated_at: NOW } }, aliases: {}, names: {}, display: {} });
const kids = d.children.map(n => n.className);
if (kids.indexOf("peoplestrip") !== 0 || kids.indexOf("thread-subject") !== 1) throw new Error("strip must sit above the subject, under the sender line: " + kids);
eq(chipTexts(d), ["fab@example.com · note", "bo@example.com · note", "cy@example.com · add note"], "chip text");
if (texts(stripOf(d)).some(t => /\(\d+\)|\d+ (people|notes)/.test(String(t)))) throw new Error("the strip shows no count");
if (editors(d).length) throw new Error("no editor until a chip is clicked");
const chip = (root, start) => all(stripOf(root)).find(n => (n.className || "").includes("personchip") && n.textContent.startsWith(start));
click(chip(d, "bo@"));
if (editors(d).length !== 1) throw new Error("a chip opens its editor");
let et = texts(editors(d)[0]);
if (!et.some(t => String(t).startsWith("Written by session frontdesk on ") && t.endsWith(", not confirmed")) ||
    !et.includes("Confirm")) throw new Error("session note: label and Confirm");
if (chip(d, "bo@").getAttribute("aria-expanded") !== "true") throw new Error("open chip is pressed");
click(chip(d, "fab@"));
if (editors(d).length !== 1) throw new Error("one editor at a time");
et = texts(editors(d)[0]);
if (!et.some(t => String(t).startsWith("Written by you on ")) || et.includes("Confirm")) throw new Error("owner note: no Confirm");
if (all(editors(d)[0]).find(n => n.tagName === "TEXTAREA").value !== "a") throw new Error("editor holds the note");
click(chip(d, "fab@"));
if (editors(d).length) throw new Error("clicking the open chip closes it");
click(chip(d, "cy@"));
if (!stripOf(d).closeEditor() || editors(d).length) throw new Error("Escape (closeEditor) closes the editor");
// Saving empty text never posts; aliases show; the Ask panel no longer carries notes.
d = await openStrip({ people: ["fab@example.com"], notes: {}, aliases: { "fab@example.com": ["f@example.org"] }, names: {} });
click(chip(d, "fab@"));
if (!texts(editors(d)[0]).includes("Also f@example.org")) throw new Error("aliases");
click(byText(editors(d)[0], "Save"));
await tick();
if (stripPosts.length) throw new Error("an empty note was posted");
// An owner-typed name wins on the chip; the editor shows it with the address.
d = await openStrip({ people: ["fab@example.com"], notes: {}, aliases: {}, names: { "fab@example.com": "Fabrice" } });
eq(chipTexts(d), ["Fabrice <fab@example.com> · add note"], "typed name on the chip");
click(chip(d, "Fabrice"));
if (!texts(editors(d)[0]).includes("Fabrice (fab@example.com)")) throw new Error("typed name in the editor");
// Old-shape notes (a page and server out of step) get no editor, so no Save can overwrite them.
d = await openStrip({ people: ["fab@example.com"], notes: { "fab@example.com": "plain string" } });
click(chip(d, "fab@"));
if (all(editors(d)[0]).some(n => n.tagName === "TEXTAREA") || !texts(d).some(t => String(t).startsWith("This page is out of date")))
  throw new Error("stale notes must not be editable");
// Slack people show display names, never a raw key.
d = await openStrip({ people: [SK], notes: { [SK]: { text: "Leads infra.", author: "owner", updated_at: NOW } },
  aliases: { [SK]: ["ann lee"] }, names: {}, display: { [SK]: "Ann Lee", "ann lee": "ann lee" } });
eq(chipTexts(d), ["Ann Lee · note"], "slack chip");
click(chip(d, "Ann Lee"));
if (!texts(editors(d)[0]).includes("Ann Lee") || !texts(editors(d)[0]).includes("Also ann lee")) throw new Error("slack notes names");
if (all(editors(d)[0]).find(n => n.tagName === "TEXTAREA").placeholder !== "What should FrontDesk remember about Ann Lee?")
  throw new Error("slack notes placeholder");
noKey(stripOf(d));
// More than 6 people: 5 chips and "+N more", which shows the rest.
const many = Array.from({ length: 8 }, (_, i) => "p" + i + "@example.com");
d = await openStrip({ people: many, notes: {} });
eq(chipTexts(d), [...many.slice(0, 5).map(p => p + " · add note"), "+3 more"], "+N more");
click(chip(d, "+3 more"));
eq(chipTexts(d), many.map(p => p + " · add note"), "expanded strip");
d = await openStrip({ people: many.slice(0, 6), notes: {} });
if (chipTexts(d).length !== 6) throw new Error("six people fit without +N more");
// Ignore: one muted "People" link that expands the strip.
d = await openStrip({ people: ["fab@example.com"], notes: {} }, { ...triage, bucket: "ignore" });
const plink = all(stripOf(d)).find(n => n.textContent === "People");
if (!plink || chipTexts(d).length) throw new Error("an Ignore thread starts collapsed");
click(plink);
eq(chipTexts(d), ["fab@example.com · add note"], "Ignore strip expands");
// No one else in the thread: no strip.
d = await openStrip({ people: [], notes: {} });
if (!stripOf(d).hidden) throw new Error("empty strip must be hidden");
// Ask: no notes section; a saved "Save note for" suggestion flips the chip to "· note".
let saved = false;
stripData = () => ({ advise: ADV, people: ["ann@example.com"], aliases: {}, names: {}, display: {},
  notes: saved ? { "ann@example.com": { text: "Likes lunch.", author: "owner", updated_at: NOW } } : {},
  history: [{ role: "owner", text: "What now?", author: "owner" },
            { role: "assistant", text: "Say yes.", note_suggestions: [{ who: "ann@example.com", text: "Likes lunch." }] }] });
ctx.fetch = async (url, opts) => {
  if (String(url).startsWith("/api/ask?")) return { ok: true, json: async () => stripData() };
  if (url === "/api/action") { stripPosts.push(JSON.parse(opts.body)); saved = true; return { ok: true, json: async () => ({ status: "done" }) }; }
  return { ok: true, json: async () => [] };
};
const asks = [];
const realFetch = ctx.fetch;
ctx.fetch = async (url, opts) => { if (String(url).startsWith("/api/ask?")) asks.push(url); return realFetch(url, opts); };
d = fn("buildDetail")(item, triage);
await tick(); await tick();
eq(chipTexts(d), ["ann@example.com · add note"], "before the suggestion");
const askDet = all(d).find(n => n.className === "ask");
askDet.open = true;
fire(askDet, "toggle");
await tick(); await tick(); await tick();
if (asks.length !== 1) throw new Error("Ask must reuse the thread's fetch, not fetch again: " + asks.length);
const askT = texts(askDet);
if (askT.some(t => String(t).startsWith("Your notes on these people")) || all(askDet).some(n => n.className === "personeditor" || n.className === "notes"))
  throw new Error("Ask panel still has a notes section");
click(byText(askDet, "Save note for ann@example.com: Likes lunch."));
await tick(); await tick(); await tick();
if (stripPosts.at(-1).kind !== "note_suggestion") throw new Error("suggestion posted");
eq(chipTexts(d), ["ann@example.com · note"], "a saved suggestion flips the chip");
console.log("js smoke ok");
// History folds into turns: a second opinion joins the turn it reviews.
const turns = vm.runInContext("groupTurns", ctx)([
  { role: "owner", text: "First?", author: "owner" }, { role: "assistant", text: "A1" },
  { role: "owner", text: "Give me a second opinion on your colleague's last answer above", author: "owner" },
  { role: "assistant", text: "A2" },
  { role: "owner", text: "Next?", author: "owner" }, { role: "assistant", text: "A3" }]);
if (turns.length !== 2 || turns[0].entries.length !== 4) throw new Error("turn grouping");
console.log("turns ok");
// ---- A saved Gmail draft is read from Gmail when the thread opens and fills the reply box,
// unless the owner has already typed; a failed check says so instead of failing silently.
{
  const findTa = d => all(d).find(n => n.tagName === "TEXTAREA" && n.placeholder === "Write a reply");
  const findBtn = (d, t) => all(d).find(n => n.tagName === "BUTTON" && n.textContent === t);
  const drafts = [];
  ctx.fetch = async url => {
    if (String(url).startsWith("/api/gmail-draft?")) { drafts.push(url);
      return { ok: true, json: async () => ({ draft: { body: "My edited draft.\n\nBest,\nAlex", url: "x" } }) }; }
    return { ok: true, json: async () => [] };
  };
  const d1 = fn("buildDetail")(item, triage);
  await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
  if (drafts.length !== 1 || !drafts[0].includes("item=gmail%3At1")) throw new Error("draft fetch: " + drafts);
  if (findTa(d1).value !== "My edited draft.\n\nBest,\nAlex") throw new Error("draft not loaded: " + findTa(d1).value);
  if (!texts(d1).includes("Your Gmail draft: edit, then save or send")) throw new Error("draft label");
  const saved = findBtn(d1, "Saved");
  if (!saved || !saved.disabled) throw new Error("a loaded draft starts as Saved");
  // Typed before Gmail answered: kept.
  let release;
  ctx.fetch = async url => {
    if (String(url).startsWith("/api/gmail-draft?")) { await new Promise(r => { release = r; });
      return { ok: true, json: async () => ({ draft: { body: "Old draft.", url: "x" } }) }; }
    return { ok: true, json: async () => [] };
  };
  const d2 = fn("buildDetail")(item, triage);
  findTa(d2).value = "I am typing.";
  await new Promise(r => setTimeout(r, 0)); release(); await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
  if (findTa(d2).value !== "I am typing.") throw new Error("a loaded draft overwrote typing");
  // Gmail unreachable: the proposal stays and a note says why.
  ctx.fetch = async url => String(url).startsWith("/api/gmail-draft?")
    ? { ok: false, status: 502, json: async () => ({ error: "Gmail did not answer" }) }
    : { ok: true, json: async () => [] };
  const d3 = fn("buildDetail")(item, triage);
  await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
  if (findTa(d3).value !== "Yes.") throw new Error("proposal lost on a failed draft check");
  if (!texts(d3).includes("Couldn't check Gmail for a saved draft: Gmail did not answer")) throw new Error("silent draft failure");
  // Slack threads never ask Gmail.
  drafts.length = 0;
  ctx.fetch = async url => { if (String(url).startsWith("/api/gmail-draft?")) drafts.push(url); return { ok: true, json: async () => [] }; };
  fn("buildDetail")({ ...item, id: "slack:C1:1", source: "slack" }, triage);
  await new Promise(r => setTimeout(r, 0));
  if (drafts.length) throw new Error("a Slack thread asked Gmail for a draft");
}
console.log("drafts ok");
// ---- Search: typing filters synced threads; Gmail results show beside them, unranked, and a
// thread already in FrontDesk is not listed twice.
{
  const rows = [{ item, triage }, { item: { ...item, id: "gmail:t2", subject: "Invoice", messages: [] }, triage: null }];
  vm.runInContext("query = 'lunch'; gmailSearch = null", ctx);
  let main = new Node("main"), counts = new Node("ul");
  fn("renderSearch")(rows, main, counts);
  let tx = texts(main);
  if (!tx.includes("FrontDesk") || !tx.includes("Lunch") || tx.includes("Invoice"))
    throw new Error("local search filter: " + tx.join("|"));
  if (!tx.includes("Press Enter to search all of Gmail, archived mail included.")) throw new Error("search hint");
  const tabs = all(main).filter(n => n.attrs && n.attrs.role === "tab");
  if (tabs.map(t => t.attrs["aria-selected"]).join() !== "true,false") throw new Error("tabs: FrontDesk selected, Gmail next");
  vm.runInContext(`gmailSearch = { q: 'lunch', results: [
    { id: 'gmail:t1', subject: 'Lunch', sender: 'Ann <ann@example.com>', updated_at: '2026-10-01T00:00:00Z', messages: 1 },
    { id: 'gmail:old', subject: 'Lunch in 2024', sender: 'Bo <bo@example.com>', updated_at: '2024-01-01T00:00:00Z',
      messages: 3, in_inbox: false, url: 'https://mail.google.com/mail/?authuser=x#all/old' }] }`, ctx);
  main = new Node("main"); counts = new Node("ul");
  fn("renderSearch")(rows, main, counts);
  tx = texts(main);
  if (!tx.includes("Gmail") || !tx.includes("Lunch in 2024") || !tx.includes("Archived, 3 messages. Not ranked."))
    throw new Error("gmail results: " + tx.join("|"));
  const res = all(main).filter(n => (n.className || "").split(" ").includes("result"));
  if (res.length !== 1) throw new Error("a synced thread was listed twice");
  vm.runInContext("gmailSearch = { q: 'lunch', error: 'Gmail did not answer' }", ctx);
  main = new Node("main");
  fn("renderSearch")(rows, main, new Node("ul"));
  if (!texts(main).includes("Couldn't search Gmail: Gmail did not answer")) throw new Error("silent search failure");
  vm.runInContext("query = ''; gmailSearch = null", ctx);
}
console.log("search ok");
// ---- Keep from search: a result opens in place (read from Gmail, plain text, Keep button);
// a kept thread is listed under From search, above Needs you.
{
  const fetched = [];
  ctx.fetch = async url => {
    fetched.push(String(url));
    if (String(url).startsWith("/api/search/thread?")) return { ok: true, json: async () => ({ item: {
      messages: [{ sender: "Bo <bo@example.com>", sent_at: "2024-01-01T00:00:00Z", body: "Old lunch plan.", has_html: true }] } }) };
    return { ok: true, json: async () => [] };
  };
  const card = fn("buildResultCard")({ id: "gmail:old", subject: "Lunch in 2024", sender: "Bo <bo@example.com>",
    updated_at: "2024-01-01T00:00:00Z", messages: 1, url: "https://mail.google.com/mail/?authuser=x#all/old" });
  const row = card.children.find(n => n.tagName === "BUTTON");
  (row.listeners.click || []).forEach(f => f());
  await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
  const tx = texts(card);
  if (!fetched.some(u => u === "/api/search/thread?id=gmail%3Aold")) throw new Error("preview fetch: " + fetched);
  for (const want of ["Old lunch plan.", "Keep in FrontDesk", "Open in Gmail"])
    if (!tx.includes(want)) throw new Error("preview lacks " + want + ": " + tx.join("|"));
  if (all(card).some(n => n.tagName === "IFRAME")) throw new Error("a preview must never frame sender HTML");
  const rowsK = [{ item: { ...item, id: "gmail:k1", subject: "Kept one", kept: true }, triage }, { item, triage }];
  const fakeMain = new Node("main"), fakeCounts = new Node("ul");
  ctx.document.getElementById = id => id === "main" ? fakeMain : id === "counts" ? fakeCounts : new Node("div");
  fn("render")(rowsK);
  const order = fakeMain.children.map(sc => sc.attrs["aria-label"]);
  if (order[0] !== "From search" || order[1] !== "Needs you") throw new Error("section order: " + order);
  ctx.document.getElementById = () => new Node("div");
}
console.log("keep ok");
// ---- Slack in search: an "In Slack" group once a search ran; a conversation FrontDesk already
// has, or a second match in the same thread, is listed once.
{
  const rows = [{ item, triage }];
  vm.runInContext(`query = 'budget'; gmailSearch = { q: 'budget', results: [], slack: [
    { id: 'gmail:t1', where: '#x', sender: 'Ann', text: 'dup of a synced id', updated_at: '2026-10-30T00:00:00Z' },
    { id: 'slack:C1:1', where: '#analytics', sender: 'Dana', text: 'Budget line by Friday?', updated_at: '2026-10-30T00:00:00Z', url: 'https://acme.slack.com/archives/C1/p1' },
    { id: 'slack:C1:1', where: '#analytics', sender: 'Theo', text: 'second match, same thread', updated_at: '2026-10-30T00:00:00Z' }],
    slack_error: '' }`, ctx);
  const main = new Node("main");
  fn("renderSearch")(rows, main, new Node("ul"));
  const tx = texts(main);
  if (!tx.includes("Slack") || !tx.includes("Budget line by Friday?") || tx.includes("second match, same thread"))
    throw new Error("slack results: " + tx.join("|"));
  vm.runInContext("gmailSearch = { q: 'budget', results: [], slack: [], slack_error: 'Slack did not answer' }", ctx);
  const main2 = new Node("main");
  fn("renderSearch")(rows, main2, new Node("ul"));
  if (!texts(main2).includes("Couldn't search Slack: Slack did not answer")) throw new Error("silent Slack failure");
  vm.runInContext("gmailSearch = { q: 'budget', results: [], slack: null }", ctx);
  const main3 = new Node("main");
  fn("renderSearch")(rows, main3, new Node("ul"));
  if (all(main3).some(n => n.attrs && n.attrs.id === "searchtab-slack")) throw new Error("no Slack tab without Slack");
  vm.runInContext("query = ''; gmailSearch = null", ctx);
}
console.log("slack search ok");
