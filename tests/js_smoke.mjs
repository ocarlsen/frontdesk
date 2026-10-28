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
const ctx = { document, window: {}, console, setTimeout, clearTimeout, crypto: globalThis.crypto,
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
console.log("js smoke ok");
