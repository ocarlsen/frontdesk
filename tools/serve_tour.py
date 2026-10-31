"""Serves the two pages the tour film drives, on synthetic data only, and prints their URLs.

    .venv/bin/python tools/serve_tour.py

Prints one JSON line, {"static": URL, "live": URL}, then serves until stdin closes (the tour
recorder starts it as a child process and closes stdin when it is done).

- static: the exported public demo (`frontdesk export-demo`), for the inbox, threads,
  shortcuts and Send (which in the demo sends nothing).
- live: the real server on a throwaway store in a temp FRONTDESK_HOME, for Ask and Memory. It is
  seeded with the demo inbox plus the synthetic a07 eval thread, its note (written by a helper
  session), the model's recorded answer from the 2026-10-29 Opus 5.5 attribution run, two "What's
  going on" items and two named people. Ask's model list is stubbed empty, so nothing asks the
  Keychain whether a key exists, and nothing here calls a model.

Both bind 127.0.0.1 only. The real ~/.frontdesk is never read: FRONTDESK_HOME is set before
frontdesk.config is imported, and the script refuses to run if that did not take."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
from datetime import UTC, datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
A07 = ROOT / "evals/attribution/a07-cookie-day-allergy.json"
A07_RUN = ROOT / "evals/results/attribution-2026-10-29-claude-opus-5-5.json"
PROFILE = ("I lead the data platform team. Vendor and budget decisions are mine and need a "
           "reply within a day. Anything about Jordan's school comes first.")
SITUATION = [("Picking the Q1 analytics vendor; Finance needs the number by Friday.", "owner"),
             ("Signed SOW for Meridian Works is waiting on legal.", "session:helper")]


def seed(store, now: datetime) -> None:
    """The demo inbox plus the a07 thread, its note and one Ask exchange with the recorded
    answer for the labelled ("session") condition."""
    from frontdesk.demo import load_demo
    from frontdesk.items import Item, Message, Triage
    load_demo(store, now=now)
    sc = json.loads(A07.read_text())
    run = json.loads(A07_RUN.read_text())
    answer = next(c["answer"] for c in run["cases"]
                  if c["scenario"] == sc["id"] and c["condition"] == "session")
    it = sc["item"]
    store.upsert_item(Item(id=it["id"], source="gmail", account=it["account"],
                           subject=it["subject"], participants=it["participants"],
                           updated_at=it["updated_at"], labels=it["labels"],
                           messages=[Message(m["sender"], m["sent_at"], m["body"],
                                             is_mine=m["is_mine"]) for m in it["messages"]]))
    store.save_triage(Triage(item_id=it["id"], bucket="needs_you", urgency=4,
                             reason="Form for a peanut butter baking day; check against the "
                                    "allergy plan.",
                             proposed_reply="", model="anthropic:claude-opus-5-5",
                             triaged_at=it["updated_at"], item_updated_at=it["updated_at"],
                             summary="Ms. Okafor asks families to sign a form for a peanut "
                                     "butter cookie baking afternoon on Thursday."))
    store.save_note(sc["note"]["who"], sc["note"]["text"], "session:helper")
    store.save_note("rafael.duarte@meridianworks.example.org",
                    "Runs the Q1 integration project at Meridian Works. Prefers one email "
                    "with all of legal's changes.", "owner")
    rafael = next(p for p in store.people_all()
                  if "rafael.duarte@meridianworks.example.org" in p["addresses"])
    store.set_person_name(rafael["id"], "Rafael Duarte", "owner")
    for text, author in SITUATION:
        store.add_situation(text, author)
    store.add_ask(it["id"], "owner", sc["question"], "owner")
    store.add_ask(it["id"], "assistant", answer, "owner",
                  {"draft_reply": "", "note_suggestions": [], "situation_suggestions": [],
                   "model": "claude-opus-5-5", "cost_usd": None})


def _quiet(handler):
    class Quiet(handler):
        def log_message(self, *a):
            pass
    return Quiet


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="fd-tour-"))
    home = work / "home"
    os.environ["FRONTDESK_HOME"] = str(home)
    sys.path.insert(0, str(ROOT))
    from frontdesk import config
    if Path(config.HOME) != home:
        raise SystemExit("frontdesk.config did not pick up the temp FRONTDESK_HOME; refusing")
    from frontdesk.export import export_demo
    from frontdesk.store import Store
    from frontdesk.web import server
    config.ensure_home()
    config.SETTINGS_PATH.write_text(json.dumps({
        "mark_read_on_open": False, "auto_sync_minutes": 0, "owner_profile": PROFILE,
        "reply_signoff": "Best,\nAlex"}))
    now = datetime.now(UTC)

    site = work / "site"
    export_demo(site, now=now)
    static = ThreadingHTTPServer(("127.0.0.1", 0),
                                 partial(_quiet(SimpleHTTPRequestHandler), directory=str(site)))
    threading.Thread(target=static.serve_forever, daemon=True).start()

    server.available_models = lambda _settings: []   # no Keychain lookups for Ask's model list
    db = work / "tour.db"
    st = Store(db)
    seed(st, now)
    st.db.close()
    app = server.make_server(Store(db), "127.0.0.1", 0, settings={})
    threading.Thread(target=app.serve_forever, daemon=True).start()

    print(json.dumps({"static": f"http://127.0.0.1:{static.server_address[1]}/index.html",
                      "live": f"http://127.0.0.1:{app.server_address[1]}/index.html"}),
          flush=True)
    try:
        sys.stdin.read()          # until the parent closes our stdin
    finally:
        static.shutdown()
        app.shutdown()
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
