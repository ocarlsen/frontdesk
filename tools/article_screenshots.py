"""Screenshots for the memory article, staged on synthetic data with the REAL page and server.

Seeds a throwaway FrontDesk home with one synthetic eval thread (evals/attribution/a07), a note
written by a helper session, and one Ask exchange whose answer is the model's actual answer from
the 2026-10-29 Opus 5.5 attribution run: the unlabelled-prompt answer for "before", the labelled
one for "after". No model call, no network, no real mail, and Ask's model list is stubbed empty so
nothing asks the Keychain about keys. Captured with tools/capture.mjs (Playwright, 2x; run `npm ci`
in tests/e2e once). Writes docs/site/article-before.jpg and article-after.jpg.
Usage: PYTHONPATH=. .venv/bin/python tools/article_screenshots.py"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="fd-article-"))
os.environ["FRONTDESK_HOME"] = str(TMP / "home")

from frontdesk import config  # noqa: E402  (FRONTDESK_HOME must be set first)
from frontdesk.items import Item, Message, Triage  # noqa: E402
from frontdesk.store import Store  # noqa: E402
from frontdesk.web import server  # noqa: E402

STAGE = Path(__file__).parent / "article_screenshots/stage.js"
SCENARIO = json.loads((ROOT / "evals/attribution/a07-cookie-day-allergy.json").read_text())
REPORT = json.loads(
    (ROOT / "evals/results/attribution-2026-10-29-claude-opus-5-5.json").read_text())


def answer(condition: str) -> str:
    return next(c["answer"] for c in REPORT["cases"]
                if c["scenario"] == SCENARIO["id"] and c["condition"] == condition)


def seed(db: Path, condition: str) -> None:
    it = SCENARIO["item"]
    s = Store(db)
    s.upsert_item(Item(id=it["id"], source="gmail", account=it["account"], subject=it["subject"],
                       participants=it["participants"], updated_at=it["updated_at"],
                       labels=it["labels"],
                       messages=[Message(m["sender"], m["sent_at"], m["body"], is_mine=m["is_mine"])
                                 for m in it["messages"]]))
    s.save_triage(Triage(item_id=it["id"], bucket="needs_you", urgency=4,
                         reason="Form for a peanut butter baking day; check against the "
                                "allergy plan.",
                         proposed_reply="", model="anthropic:claude-opus-5-5",
                         triaged_at="2026-10-28T09:00:00Z", item_updated_at=it["updated_at"],
                         summary="Ms. Okafor asks families to sign a form for a peanut butter "
                                 "cookie baking afternoon on Thursday."))
    s.save_note(SCENARIO["note"]["who"], SCENARIO["note"]["text"], "session:helper")
    # Date the note to the eval run, so its label reads the same on every re-run.
    s.db.execute("UPDATE people SET created_at=?, updated_at=?", ("2026-10-29T09:00:00Z",) * 2)
    s.db.commit()
    s.add_ask(it["id"], "owner", SCENARIO["question"], "owner")
    s.add_ask(it["id"], "assistant", answer(condition), "owner",
              {"draft_reply": "", "note_suggestions": [], "situation_suggestions": [],
               "model": "claude-opus-5-5", "cost_usd": None})
    s.db.close()


def main() -> None:
    if Path(config.HOME) != TMP / "home":
        raise SystemExit("frontdesk.config did not pick up the temp FRONTDESK_HOME; refusing")
    config.ensure_home()
    config.SETTINGS_PATH.write_text(
        json.dumps({"mark_read_on_open": False, "auto_sync_minutes": 0}))
    server.available_models = lambda _settings: []   # no Keychain lookups for Ask's model list
    shots = [("before", "baseline_session", ""), ("after", "session", "?notes=1")]
    for name, condition, query in shots:
        db = TMP / f"{name}.db"
        seed(db, condition)
        httpd = server.make_server(Store(db), "127.0.0.1", 0, settings={})
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        out = ROOT / f"docs/site/article-{name}.jpg"
        try:
            subprocess.run(["node", str(ROOT / "tools/capture.mjs"),
                            f"http://127.0.0.1:{httpd.server_address[1]}/index.html{query}",
                            str(out), "760", "auto", str(STAGE)], check=True)
        finally:
            httpd.shutdown()
    shutil.rmtree(TMP)

if __name__ == "__main__":
    main()
