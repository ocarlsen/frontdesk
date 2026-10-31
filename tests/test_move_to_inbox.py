"""Move to inbox: a kept Gmail thread outside the inbox goes back to Gmail's inbox, stays kept
(so sync keeps it current past the sync window), and leaves the From search section."""
from __future__ import annotations

import pytest
from test_actions import FakeGmail

from frontdesk import actions
from frontdesk.items import Item, Message
from frontdesk.store import Store
from frontdesk.web import server


class ModGmail(FakeGmail):
    def __init__(self):
        super().__init__()
        self.mods = []

    def modify_thread(self, tid, add=(), remove=()):
        self.mods.append((tid, list(add), list(remove)))
        return {}


def kept_store(tmp_path, labels=("CATEGORY_PERSONAL",)):
    s = Store(tmp_path / "s.db")
    s.keep(Item(id="gmail:t1", source="gmail", account="owner@example.com", subject="Old deal",
                participants=[], updated_at="2024-01-01T00:00:00Z", labels=list(labels),
                messages=[Message("Ann <ann@example.com>", "2024-01-01T00:00:00Z", "hi")]))
    return s


def test_moves_it_into_gmails_inbox_and_keeps_it(tmp_path):
    s, g = kept_store(tmp_path), ModGmail()
    out = actions.move_to_inbox(s, "gmail:t1", g, "click-0001")
    assert out["status"] == "done" and g.mods == [("t1", ["INBOX"], [])]
    assert "INBOX" in s.get_item("gmail:t1").labels and s.is_kept("gmail:t1")
    assert s.kept_ids() == {"gmail:t1"}                    # sync keeps fetching it
    row = next(r for r in server.ranked_payload(s) if r["item"]["id"] == "gmail:t1")
    assert row["item"]["kept"] and "INBOX" in row["item"]["labels"]   # the page files it by bucket


def test_already_in_the_inbox_and_repeats_do_nothing(tmp_path):
    s, g = kept_store(tmp_path, labels=("INBOX",)), ModGmail()
    assert actions.move_to_inbox(s, "gmail:t1", g, "click-0001")["status"] == "already_done"
    assert g.mods == []


def test_slack_and_bad_keys_are_refused(tmp_path):
    s = kept_store(tmp_path)
    with pytest.raises(actions.ActionError):
        actions.move_to_inbox(s, "gmail:t1", ModGmail(), "x")
    s.upsert_item(Item(id="slack:C1:1.0", source="slack", account="acme.slack.com", subject="#x",
                       participants=[], updated_at="2026-10-30T00:00:00Z",
                       messages=[Message("Ann", "2026-10-30T00:00:00Z", "hi")]))
    with pytest.raises(actions.ActionError, match="only a Gmail thread"):
        actions.move_to_inbox(s, "slack:C1:1.0", None, "click-0002")
