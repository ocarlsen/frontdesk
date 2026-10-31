"""Mark unread (Shift+U): Gmail gets UNREAD back; Slack keeps the mark in FrontDesk, through a sync,
until the owner reads it. Reply all reaches the draft and the send."""
from __future__ import annotations

from test_actions import FakeGmail, store_with_item

from frontdesk import actions
from frontdesk.store import Store
from frontdesk.web import server


class ModGmail(FakeGmail):
    def __init__(self):
        super().__init__()
        self.mods = []

    def modify_thread(self, tid, add=(), remove=()):
        self.mods.append((tid, list(add), list(remove)))
        return {}


def test_gmail_mark_unread_adds_the_label_in_gmail_and_here(tmp_path):
    s, g = store_with_item(tmp_path), ModGmail()
    assert actions.mark_unread(s, "gmail:t1", g)["status"] == "done"
    assert g.mods == [("t1", ["UNREAD"], [])]
    assert "UNREAD" in s.get_item("gmail:t1").labels
    actions.mark_read(s, "gmail:t1", g)
    assert g.mods[-1] == ("t1", [], ["UNREAD"]) and "UNREAD" not in s.get_item("gmail:t1").labels


def test_slack_unread_is_kept_here_and_survives_a_sync(tmp_path):
    from frontdesk.items import Item, Message
    s = Store(tmp_path / "s.db")
    item = Item(id="slack:C1:1.0", source="slack", account="acme.slack.com", subject="#x", participants=[],
                updated_at="2026-10-30T00:00:00Z", messages=[Message("Ann", "2026-10-30T00:00:00Z", "hi")])
    s.upsert_item(item)
    actions.mark_unread(s, item.id, None)
    s.upsert_item(item)                                   # a sync rewrites labels from Slack
    row = next(r for r in server.ranked_payload(s) if r["item"]["id"] == item.id)
    assert "UNREAD" in row["item"]["labels"]
    actions.mark_read(s, item.id, None)
    row = next(r for r in server.ranked_payload(s) if r["item"]["id"] == item.id)
    assert "UNREAD" not in row["item"]["labels"]


def test_reply_all_reaches_the_draft():
    from frontdesk import drafting
    seen = {}

    class G(FakeGmail):
        def get_thread(self, tid):
            return {"id": tid, "messages": [{"id": "m1", "internalDate": "1", "labelIds": ["INBOX"],
                    "payload": {"headers": [{"name": "From", "value": "Ann <ann@example.com>"},
                                            {"name": "To", "value": "owner@example.com, bo@example.com"},
                                            {"name": "Subject", "value": "Lunch"},
                                            {"name": "Message-ID", "value": "<m1@x>"}]}}]}

        def create_draft(self, body):
            seen["raw"] = body
            return {"id": "d1", "message": {"id": "mm", "threadId": "t1"}}

    import base64
    drafting.save_reply(G(), "t1", "Yes.", reply_all=True)
    raw = base64.urlsafe_b64decode(seen["raw"]["message"]["raw"])
    assert b"Cc: bo@example.com" in raw
