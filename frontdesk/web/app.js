"use strict";
// FrontDesk UI. Every string from /api/items comes from email and is untrusted: it reaches the
// DOM only through textContent / createTextNode. The single exception is item.url, used as an
// href only after a prefix check against Gmail's origin.

const SECTIONS = [
  { key: "needs_you", title: "Needs you", collapsed: false },
  { key: "fyi", title: "FYI", collapsed: false },
  { key: "ignore", title: "Ignore", collapsed: true },
  { key: "untriaged", title: "Not triaged yet", collapsed: false },
];
const GMAIL_PREFIX = "https://mail.google.com/";

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}

function parseSender(s) {
  // "Jane Doe <jane@example.com>" -> {name, addr}; "<a@b>" or "a@b" -> name falls back to addr.
  const m = /^\s*"?([^"<]*?)"?\s*<([^>]*)>\s*$/.exec(s || "");
  if (m) return { name: m[1] || m[2], addr: m[2] };
  return { name: s || "Unknown sender", addr: "" };
}

function senderName(s) {
  return parseSender(s).name;
}

function gmailTime(iso) {
  // Gmail's header style: "10:02 AM (1 hour ago)", or "Oct 21, 10:02 AM" when older.
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const d = new Date(t);
  const sameDay = d.toDateString() === new Date().toDateString();
  const clock = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  if (!sameDay) return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) + ", " + clock;
  return clock + " (" + relTime(iso) + ")";
}

function messageFrame(itemId, index) {
  // The email's own HTML, served by /msg under a no-script, no-remote-load CSP. sandbox has no
  // allow-scripts, so nothing in the mail can run; allow-same-origin only lets this page read
  // the frame's height, and allow-popups lets links open in a new tab.
  const f = document.createElement("iframe");
  f.className = "mailframe";
  f.setAttribute("sandbox", "allow-same-origin allow-popups allow-popups-to-escape-sandbox");
  f.setAttribute("referrerpolicy", "no-referrer");
  f.title = "Message";
  f.src = "/msg?item=" + encodeURIComponent(itemId) + "&i=" + index;
  f.addEventListener("load", () => {
    const doc = f.contentDocument;
    if (doc && doc.documentElement) f.style.height = (doc.documentElement.scrollHeight + 4) + "px";
  });
  return f;
}

function relTime(iso) {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const s = Math.round((Date.now() - t) / 1000);
  if (s < 60) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return m + "m ago";
  const h = Math.round(m / 60);
  if (h < 24) return h + "h ago";
  const d = Math.round(h / 24);
  if (d < 7) return d + "d ago";
  return new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function absTime(iso) {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? "" : new Date(t).toLocaleString();
}

function safeGmailUrl(u) {
  return typeof u === "string" && u.startsWith(GMAIL_PREFIX) ? u : null;
}

function buildDetail(item, triage) {
  const d = el("div", "detail");
  const msgs = Array.isArray(item.messages) ? item.messages : [];
  d.append(el("h2", "thread-subject", item.subject || "(no subject)"));
  msgs.forEach((m, i) => {
    const box = el("div", m.is_mine ? "msg mine" : "msg");
    const head = el("div", "msg-head");
    const who = parseSender(m.sender);
    const avatar = el("span", "avatar", (who.name.trim()[0] || "?").toUpperCase());
    const ident = el("div", "ident");
    const line = el("div", "who");
    line.append(el("span", "from", who.name));
    if (who.addr && who.addr !== who.name) line.append(el("span", "addr", "<" + who.addr + ">"));
    ident.append(line);
    head.append(avatar, ident, el("span", "at", gmailTime(m.sent_at)));
    box.append(head, m.has_html ? messageFrame(item.id, i) : el("p", "body", m.body || ""));
    d.append(box);
  });
  const reply = el("div", "reply");
  const actions = el("div", "actions");
  const text = triage && triage.proposed_reply ? triage.proposed_reply : "";
  if (text) {
    const id = "reply-" + Math.random().toString(36).slice(2);
    const label = el("label", null, "Proposed reply");
    label.htmlFor = id;
    const ta = el("textarea");
    ta.id = id;
    ta.readOnly = true;
    ta.value = text;
    const copy = el("button", "btn primary", "Copy reply");
    copy.type = "button";
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(text);
        copy.textContent = "Copied";
      } catch (e) {
        ta.select();
        copy.textContent = "Select and copy manually";
      }
      setTimeout(() => { copy.textContent = "Copy reply"; }, 1800);
    });
    reply.append(label, ta);
    actions.append(copy);
  } else {
    reply.append(el("p", "note", triage ? "No reply suggested." : "Not triaged yet."));
  }
  if (triage) d.append(whyPanel(triage));
  const arch = el("button", "btn", "Archive");
  arch.type = "button";
  arch.addEventListener("click", () => archive(item, arch));
  actions.append(arch);
  const url = safeGmailUrl(item.url);
  if (url) {
    const a = el("a", "btn", "Open in Gmail");
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    actions.append(a);
  }
  if (actions.childNodes.length) reply.append(actions);
  d.append(reply);
  return d;
}

function buildCard(item, triage) {
  const li = el("li", "card");
  const row = el("button", "row");
  row.type = "button";
  row.setAttribute("aria-expanded", "false");

  const urg = triage ? Math.max(1, Math.min(5, Number(triage.urgency) || 1)) : 0;
  const dot = el("span", urg ? "dot u" + urg : "dot none");
  dot.title = urg ? "Urgency " + urg + " of 5" : "Not triaged";

  const msgs = Array.isArray(item.messages) ? item.messages : [];
  const newest = msgs.length ? msgs[msgs.length - 1] : null;
  const meta = el("span", "meta");
  const line1 = el("span", "line1");
  line1.append(el("span", "sender", senderName(newest ? newest.sender : "")),
               el("span", "subject", item.subject || "(no subject)"));
  meta.append(line1);
  if (triage && triage.reason) meta.append(el("span", "reason", triage.reason));

  const when = el("span", "when", relTime(item.updated_at));
  when.title = absTime(item.updated_at);
  row.append(dot, meta, when);

  let detail = null;
  row.addEventListener("click", () => {
    const open = row.getAttribute("aria-expanded") === "true";
    if (open) {
      detail.hidden = true;
    } else {
      if (!detail) { detail = buildDetail(item, triage); li.append(detail); }
      detail.hidden = false;
    }
    row.setAttribute("aria-expanded", String(!open));
    li.classList.toggle("open", !open);
  });
  li.append(row);
  return li;
}

function clickKey() {
  // One key per click, so the server can tell a double-click from a deliberate second action.
  // getRandomValues works on plain-http pages, where crypto.randomUUID does not.
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  return Array.from(b, x => x.toString(16).padStart(2, "0")).join("");
}

async function postAction(kind, itemId) {
  const res = await fetch("/api/action", {
    method: "POST",
    headers: { "X-FrontDesk": "action", "Content-Type": "application/json" },
    body: JSON.stringify({ kind, item_id: itemId, key: clickKey() }),
  });
  const out = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(out.error || "HTTP " + res.status);
  return out;
}

let toastTimer = null;
function toast(text, undoLabel, onUndo) {
  const t = document.getElementById("toast");
  t.replaceChildren(el("span", null, text));
  if (onUndo) {
    const u = el("button", "linkbtn", undoLabel);
    u.type = "button";
    u.addEventListener("click", () => { t.hidden = true; onUndo(); });
    t.append(u);
  }
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 10000);
}

async function archive(item, btn) {
  btn.disabled = true;
  try {
    await postAction("archive", item.id);
    await load();
    toast("Archived: " + (item.subject || "(no subject)"), "Undo", async () => {
      try {
        await postAction("unarchive", item.id);
        await load();
        toast("Moved back to the inbox.");
      } catch (e) {
        toast("Undo failed: " + e.message);
      }
    });
  } catch (e) {
    btn.disabled = false;
    toast("Archive failed: " + e.message);
  }
}

function whyPanel(t) {
  // Provenance for one ranking: enough to inspect it, price it and replay it on another model.
  const det = el("details", "why");
  det.append(el("summary", null, "Why this ranking"));
  const dl = el("dl");
  const band = t.urgency >= 5 ? "today" : t.urgency >= 3 ? "this week" : "whenever";
  const cost = t.cost_usd === null || t.cost_usd === undefined ? "n/a"
    : "$" + Number(t.cost_usd).toFixed(4);
  const rows = [
    ["Decision", t.bucket.replace("_", " ") + ", urgency " + t.urgency + " of 5 (" + band + ")"],
    ["Reason", t.reason],
    ["Model", t.model_served || t.model],
    ["Prompt version", t.prompt_version || "unknown"],
    ["Tokens", t.tokens_in + " in (+" + t.cache_read + " cached), " + t.tokens_out + " out"],
    ["Latency", t.latency_ms + " ms"],
    ["Est. cost", cost],
    ["Ranked", absTime(t.triaged_at)],
  ];
  for (const [k, v] of rows) dl.append(el("dt", null, k), el("dd", null, v));
  det.append(dl);
  return det;
}

function expandAllButton(ul) {
  // Opens (or closes) every thread in one section by driving each row's own toggle, so expand
  // state and lazy detail-building stay in one code path.
  const b = el("button", "linkbtn", "Expand all");
  b.type = "button";
  b.addEventListener("click", () => {
    const rows = [...ul.querySelectorAll(":scope > li > .row")];
    const anyClosed = rows.some(r => r.getAttribute("aria-expanded") !== "true");
    for (const r of rows) {
      if ((r.getAttribute("aria-expanded") === "true") !== anyClosed) r.click();
    }
    b.textContent = anyClosed ? "Collapse all" : "Expand all";
  });
  return b;
}

function render(rows) {
  const main = document.getElementById("main");
  const counts = document.getElementById("counts");
  main.replaceChildren();
  counts.replaceChildren();

  const groups = Object.fromEntries(SECTIONS.map(s => [s.key, []]));
  for (const r of rows) {
    const key = r.triage && groups[r.triage.bucket] ? r.triage.bucket : "untriaged";
    groups[key].push(r);
  }

  if (!rows.length) {
    const p = el("p", "status", "Nothing synced yet. Run: ");
    p.append(el("code", null, "frontdesk sync"));
    main.append(p);
    return;
  }

  for (const s of SECTIONS) {
    const list = groups[s.key];
    if (s.key !== "untriaged" || list.length) {
      const c = el("li");
      c.append(el("b", null, String(list.length)), document.createTextNode(" " + s.title));
      counts.append(c);
    }
    if (!list.length) continue;
    const sec = el("section");
    sec.setAttribute("aria-label", s.title);
    const ul = el("ul", "list");
    for (const r of list) ul.append(buildCard(r.item, r.triage));
    const toggle = expandAllButton(ul);
    if (s.collapsed) {
      const det = el("details");
      const sum = el("summary", null, s.title + " (" + list.length + ")");
      det.append(sum, toggle, ul);
      sec.append(det);
    } else {
      const head = el("div", "sechead");
      head.append(el("h2", null, s.title), toggle);
      sec.append(head, ul);
    }
    main.append(sec);
  }
}

async function load() {
  const status = document.getElementById("status");
  try {
    const res = await fetch("/api/items", { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    render(await res.json());
  } catch (e) {
    status.textContent = "Could not load items: " + e.message;
  }
}

async function syncNow() {
  const btn = document.getElementById("sync");
  const note = document.getElementById("syncnote");
  btn.disabled = true;
  btn.textContent = "Syncing...";
  note.textContent = "";
  try {
    const res = await fetch("/api/sync", { method: "POST", headers: { "X-FrontDesk": "sync" } });
    const out = await res.json();
    if (!res.ok) throw new Error(out.error || "HTTP " + res.status);
    let msg = "Synced " + out.synced + ", removed " + out.removed + ", ranked " + out.triaged;
    if (out.failed) msg += ", " + out.failed + " failed";
    if (out.triage_error) msg += ". Ranking skipped: " + out.triage_error;
    note.textContent = msg;
    await load();
  } catch (e) {
    note.textContent = "Sync failed: " + e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "Sync";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("sync").addEventListener("click", syncNow);
  load();
});
