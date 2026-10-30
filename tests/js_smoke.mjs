// Runs app.js against a tiny stub DOM and builds a card and its detail view, so a runtime error
// in the page (not just a syntax error) fails the test suite. Usage: node tests/js_smoke.mjs [path/to/app.js]
import { readFileSync } from "node:fs";
import vm from "node:vm";

class Node {
  constructor(tag) {
    this.tagName = (tag || "").toUpperCase(); this.children = []; this.attrs = {};
    this.dataset = {}; this.style = {}; this.listeners = {}; this.textContent = "";
    this.classList = { add() {}, remove() {}, toggle() {}, contains: () => false };
    this.hidden = false; this.value = ""; this.disabled = false;
  }
  get childNodes() { return this.children; }
  append(...c) { this.children.push(...c); }
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
const notes = new Node("div");
fn("renderNotes")(notes, ["fab@example.com", "bo@example.com", "cy@example.com"], {
  "fab@example.com": { text: "a", author: "owner", updated_at: "2026-10-28T16:00:00Z" },
  "bo@example.com": { text: "b", author: "session:frontdesk", updated_at: "2026-10-28T16:00:00Z" },
}, () => {});
const nt = texts(notes);
if (!nt.some(t => t.startsWith("Written by you on "))) throw new Error("no owner label");
if (!nt.some(t => t.startsWith("Written by session frontdesk on ") && t.endsWith(", not confirmed")))
  throw new Error("no session label");
if (nt.filter(t => t === "Confirm").length !== 1) throw new Error("Confirm only on the session note");
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
// Old-shape notes (a page and server out of step) get no editor, so no Save can overwrite them.
const stale = new Node("div");
fn("renderNotes")(stale, ["fab@example.com"], { "fab@example.com": "plain string" }, () => {});
const all = n => [n, ...n.children.flatMap(all)];
if (all(stale).some(n => n.tagName === "TEXTAREA") || !texts(stale).some(t => t.startsWith("This page is out of date")))
  throw new Error("stale notes must not be editable");
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
// Saving an empty note never posts (empty text no longer deletes).
posted.length = 0;
const en = new Node("div");
fn("renderNotes")(en, ["fab@example.com"], {}, () => {}, { "fab@example.com": ["f@example.org"] }, {});
if (!texts(en).includes("Also f@example.org")) throw new Error("aliases");
click(byText(en, "Save"));
await new Promise(r => setTimeout(r, 0));
if (posted.length) throw new Error("an empty note was posted");
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
const sn = new Node("div");
fn("renderNotes")(sn, [SK], { [SK]: { text: "Leads infra.", author: "owner", updated_at: "2026-10-28T16:00:00Z" } },
  () => {}, { [SK]: ["ann lee"] }, {}, { [SK]: "Ann Lee", "ann lee": "ann lee" });
if (!texts(sn).includes("Ann Lee") || !texts(sn).includes("Also ann lee")) throw new Error("slack notes names");
if (all(sn).find(n => n.tagName === "TEXTAREA").placeholder !== "What should FrontDesk remember about Ann Lee?")
  throw new Error("slack notes placeholder");
noKey(sn);
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
console.log("js smoke ok");
// History folds into turns: a second opinion joins the turn it reviews.
const turns = vm.runInContext("groupTurns", ctx)([
  { role: "owner", text: "First?", author: "owner" }, { role: "assistant", text: "A1" },
  { role: "owner", text: "Give me a second opinion on your colleague's last answer above", author: "owner" },
  { role: "assistant", text: "A2" },
  { role: "owner", text: "Next?", author: "owner" }, { role: "assistant", text: "A3" }]);
if (turns.length !== 2 || turns[0].entries.length !== 4) throw new Error("turn grouping");
console.log("turns ok");
