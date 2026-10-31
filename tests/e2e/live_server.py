"""The live FrontDesk server on the synthetic demo inbox, for the browser tests' Ask checks.

    python tests/e2e/live_server.py

Prints one JSON line, {"live": URL}, then serves on 127.0.0.1 until stdin closes (the test
runner's global setup starts it as a child and closes stdin in teardown).

Same settings as `frontdesk demo` ({"demo": True}: sync, profile and Ask's model calls are off),
on a throwaway store in a temp FRONTDESK_HOME. FD_E2E_APP_JS=<file> serves that file as app.js
(a red proof against another version of the page, as for the static demo). Ask's model list is stubbed empty, so nothing
asks the Keychain whether a key exists, and nothing here calls a model. The real ~/.frontdesk is
never read: FRONTDESK_HOME is set before frontdesk.config is imported, and the script refuses to
run if that did not take."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


# Search fixtures (synthetic, no network): a Gmail thread kept from a search and archived in
# Gmail, and fake answers for the search routes, so the browser tests can drive Move to inbox,
# the search tabs, open-in-place and Keep through the real server and page.
KEPT_ID = "gmail:e2e0000000000a01"
FOUND = [("e2e0000000000b01", "Old invoice from Harbor Supply", "Pat <pat@harbor.example.com>"),
         ("e2e0000000000b02", "Lunch next month?", "Kim <kim@example.org>")]
# What a search for "receipts" finds instead: never kept by any test, so the result-selection
# tests always see them as results: (thread, subject, sender, in the inbox, unread).
RECEIPTS = [("e2e0000000000c01", "Receipt for your order", "Shop <orders@shop.example.com>", True, True),
            ("e2e0000000000c02", "Your March receipt", "Cafe <hello@cafe.example.net>", False, False),
            ("e2e0000000000c03", "Receipt: annual plan", "Billing <billing@tools.example.com>", False, False),
            ("e2e0000000000c04", "Unread receipt, archived", "Store <hi@store.example.com>", False, True)]


# Slack matches only the Keep tests touch: a group DM and a channel thread.
SLACK_KEEPABLE = [
    {"id": "slack:G0E2E0002:dm", "kind": "group_dm", "where": "Group DM", "sender": "dana",
     "text": "the receipts are in the shared folder", "updated_at": "2025-03-01T10:00:00Z",
     "url": "https://acme.slack.com/archives/G0E2E0002/p1740000200000100"},
    {"id": "slack:C0E2E0003:1740000300.000100", "kind": "channel", "where": "#finance",
     "sender": "sam", "text": "who has the March receipts?", "updated_at": "2025-03-01T10:00:00Z",
     "url": "https://acme.slack.com/archives/C0E2E0003/p1740000300000100"},
]


def seed_search(st, server) -> None:
    from http import HTTPStatus

    from frontdesk.items import Item, Message
    old = "2025-03-01T10:00:00Z"
    st.keep(Item(id=KEPT_ID, source="gmail", account="alex@example.com",
                 subject="Kept: 2025 vendor contract", participants=["dana@example.com"],
                 updated_at=old, labels=["CATEGORY_PERSONAL"],
                 messages=[Message("Dana <dana@example.com>", old, "The signed contract is attached.")]))

    # Results moved to the inbox (the demo-mode label change is a no-op): Keep then fetches them
    # with INBOX, as Gmail would after the move.
    inboxed: set[str] = set()
    from frontdesk import actions
    real_result_op = actions.result_op

    def result_op(item_id, op, gmail):
        if op == "inbox":
            inboxed.add(item_id)
        elif op == "archive":
            inboxed.discard(item_id)
        return real_result_op(item_id, op, gmail)

    actions.result_op = result_op

    def item_for(tid: str, subject: str, sender: str) -> Item:
        inbox = ["INBOX"] if f"gmail:{tid}" in inboxed else []
        return Item(id=f"gmail:{tid}", source="gmail", account="alex@example.com", subject=subject,
                    participants=[sender.split("<")[1].rstrip(">")], updated_at=old,
                    labels=["CATEGORY_PERSONAL", *inbox],
                    messages=[Message(sender, old, f"Synthetic body of: {subject}.")])

    def run_search(settings, query, client_factory=None, slack_factory=None, db_path=None):
        q = (query or "").strip()
        if not q:
            return HTTPStatus.BAD_REQUEST, {"error": "type a search of up to 500 characters"}
        found = RECEIPTS if q == "receipts" else [(t, s, f, False, False) for t, s, f in FOUND]
        rows = [{"id": f"gmail:{t}", "subject": s, "sender": f, "from_me": False,
                 "updated_at": old, "messages": 1, "in_inbox": inbox, "unread": unread, "starred": False,
                 "url": f"https://mail.google.com/mail/?authuser=alex@example.com#all/{t}"}
                for t, s, f, inbox, unread in found]
        slack = [{"id": "slack:C0E2E0001:1740000000.000100", "kind": "channel", "where": "#ops",
                  "sender": "riley", "text": "The invoice question is answered in the thread.",
                  "updated_at": old, "url": "https://acme.slack.com/archives/C0E2E0001/p1740000000000100"},
                 {"id": "slack:C0E2E0001:1740000000.000100", "kind": "channel", "where": "#ops",
                  "sender": "sam", "text": "A second match in the same thread.", "updated_at": old,
                  "url": ""}]
        if q == "receipts":
            slack += SLACK_KEEPABLE
        return HTTPStatus.OK, {"results": rows, "gmail_error": "", "slack": slack, "slack_error": ""}

    def search_thread(settings, item_id, client_factory=None):
        for t, s, f in FOUND:
            if item_id == f"gmail:{t}":
                d = item_for(t, s, f).to_dict()
                for m in d["messages"]:
                    m["has_html"] = False
                return HTTPStatus.OK, {"item": d}
        return HTTPStatus.NOT_FOUND, {"error": "not found"}

    def keep_result(db_path, settings, item_id, client_factory=None, provider_factory=None,
                    slack_factory=None):
        from frontdesk.store import Store
        for m in SLACK_KEEPABLE:
            if item_id == m["id"]:
                store = Store(db_path)
                try:
                    store.keep(Item(id=m["id"], source="slack", account="acme.slack.com",
                                    subject=m["where"] + ": " + m["text"], participants=[],
                                    updated_at=old, labels=["slack"], url=m["url"],
                                    messages=[Message(m["sender"], old, m["text"])]))
                finally:
                    store.db.close()
                return HTTPStatus.OK, {"status": "done", "kind": "keep", "ranked": False}
        for t, s, f in FOUND + [r[:3] for r in RECEIPTS]:
            if item_id == f"gmail:{t}":
                store = Store(db_path)
                try:
                    store.keep(item_for(t, s, f))
                finally:
                    store.db.close()
                return HTTPStatus.OK, {"status": "done", "kind": "keep", "ranked": False}
        return HTTPStatus.NOT_FOUND, {"error": "not found"}

    server.run_search, server.search_thread, server.keep_result = run_search, search_thread, keep_result


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="fd-e2e-live-"))
    home = work / "home"
    os.environ["FRONTDESK_HOME"] = str(home)
    sys.path.insert(0, str(ROOT))
    from frontdesk import config
    if Path(config.HOME) != home:
        raise SystemExit("frontdesk.config did not pick up the temp FRONTDESK_HOME; refusing")
    from frontdesk.demo import load_demo
    from frontdesk.store import Store
    from frontdesk.web import server
    config.ensure_home()
    server.available_models = lambda _settings: []   # no Keychain lookups for Ask's model list
    if os.environ.get("FD_E2E_APP_JS"):
        web = work / "web"
        shutil.copytree(server.STATIC_DIR, web, ignore=shutil.ignore_patterns("*.py", "__pycache__"))
        shutil.copyfile(os.environ["FD_E2E_APP_JS"], web / "app.js")
        server.STATIC_DIR = web
    db = work / "e2e.db"
    st = Store(db)
    load_demo(st, now=datetime.now(UTC))
    seed_search(st, server)
    st.db.close()
    app = server.make_server(Store(db), "127.0.0.1", 0, settings={"demo": True})
    threading.Thread(target=app.serve_forever, daemon=True).start()
    print(json.dumps({"live": f"http://127.0.0.1:{app.server_address[1]}/index.html"}),
          flush=True)
    try:
        sys.stdin.read()          # until the parent closes our stdin
    finally:
        app.shutdown()
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
