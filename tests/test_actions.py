"""Archive and undo against a fake Gmail client: idempotency, account check, failure handling."""
from __future__ import annotations

import pytest

from frontdesk import actions
from frontdesk.gmail.client import GmailError
from frontdesk.items import Item, Message
from frontdesk.store import Store


class FakeGmail:
    def __init__(self, owner="owner@example.com", fail=False):
        self.owner, self.fail, self.calls = owner, fail, []

    def profile_email(self):
        return self.owner

    def modify_thread(self, thread_id, add=(), remove=()):
        if self.fail:
            raise GmailError(500, "threads/modify", "backend error")
        self.calls.append((thread_id, tuple(add), tuple(remove)))
        return {}


def store_with_item(tmp_path):
    store = Store(tmp_path / "a.db")
    store.upsert_item(Item(id="gmail:t1", source="gmail", account="owner@example.com",
                           subject="s", participants=[], updated_at="2026-10-28T16:00:00Z",
                           messages=[Message("a@example.com", "2026-10-28T16:00:00Z", "hi")]))
    return store


def test_archive_hides_and_calls_gmail_once_per_click(tmp_path):
    store, g = store_with_item(tmp_path), FakeGmail()
    assert actions.set_archived(store, "gmail:t1", True, g, "click-0001")["status"] == "done"
    assert actions.set_archived(store, "gmail:t1", True, g, "click-0001")["status"] == "already_done"
    assert actions.set_archived(store, "gmail:t1", True, g, "click-0002")["status"] == "already_done"
    assert g.calls == [("t1", (), ("INBOX",))]
    assert store.ranked() == []


def test_archive_undo_archive_again_works(tmp_path):
    store, g = store_with_item(tmp_path), FakeGmail()
    actions.set_archived(store, "gmail:t1", True, g, "click-0001")
    actions.set_archived(store, "gmail:t1", False, g, "click-0002")
    assert [i.id for i, _ in store.ranked()] == ["gmail:t1"]
    assert actions.set_archived(store, "gmail:t1", True, g, "click-0003")["status"] == "done"
    assert g.calls == [("t1", (), ("INBOX",)), ("t1", ("INBOX",), ()), ("t1", (), ("INBOX",))]


def test_wrong_account_token_is_refused_and_nothing_changes(tmp_path):
    store, g = store_with_item(tmp_path), FakeGmail(owner="someone-else@example.com")
    with pytest.raises(actions.ActionError, match="actions token is for"):
        actions.set_archived(store, "gmail:t1", True, g, "click-0001")
    assert g.calls == [] and len(store.ranked()) == 1
    assert store.action("archive:gmail:t1:click-0001")["status"] == "failed"


def test_gmail_failure_leaves_thread_visible_and_retry_reuses_the_row(tmp_path):
    store = store_with_item(tmp_path)
    with pytest.raises(actions.ActionError):
        actions.set_archived(store, "gmail:t1", True, FakeGmail(fail=True), "click-0001")
    assert len(store.ranked()) == 1
    assert actions.set_archived(store, "gmail:t1", True, FakeGmail(), "click-0001")["status"] == "done"
    assert store.ranked() == []


def test_demo_mode_skips_gmail(tmp_path):
    store = store_with_item(tmp_path)
    assert actions.set_archived(store, "gmail:t1", True, None, "click-0001")["status"] == "done"
    assert store.ranked() == []


def test_bad_idempotency_key_rejected(tmp_path):
    with pytest.raises(actions.ActionError, match="idempotency"):
        actions.set_archived(store_with_item(tmp_path), "gmail:t1", True, None, "x")


def test_prune_clears_hidden_rows(tmp_path):
    store = store_with_item(tmp_path)
    actions.set_archived(store, "gmail:t1", True, None, "click-0001")
    store.prune("gmail", "owner@example.com", set())
    assert not store.is_hidden("gmail:t1")


class DraftGmail(FakeGmail):
    def __init__(self, exc=None, **kw):
        super().__init__(**kw)
        self.exc, self.drafts = exc, []

    def get_thread(self, tid):
        return {"id": tid, "messages": [{
            "id": "m1", "internalDate": "1000", "labelIds": ["INBOX"],
            "payload": {"headers": [{"name": "From", "value": "Ann <ann@example.com>"},
                                    {"name": "Subject", "value": "Lunch"},
                                    {"name": "Message-ID", "value": "<m1@x>"}]}}]}

    def create_draft(self, body):
        if self.exc:
            raise self.exc
        self.drafts.append(body)
        return {"id": f"d{len(self.drafts)}", "message": {"id": "mm", "threadId": "t1"}}


SEEN = "2026-10-28T16:00:00Z"


def test_draft_saves_once_per_click(tmp_path):
    store, g = store_with_item(tmp_path), DraftGmail()
    out = actions.save_draft(store, "gmail:t1", "Thursday works.", SEEN, g, "click-0001")
    again = actions.save_draft(store, "gmail:t1", "Thursday works.", SEEN, g, "click-0001")
    assert out["draft_id"] == again["draft_id"] == "d1" and len(g.drafts) == 1
    assert store.action("draft:gmail:t1:click-0001")["status"] == "done"


@pytest.mark.parametrize("body,seen,msg", [
    ("", SEEN, "empty"),
    ("See you at [time that works].", SEEN, "bracketed"),
    ("Thursday works.", "2026-10-28T17:00:00Z", "new message arrived"),
])
def test_draft_refusals_never_reach_gmail(tmp_path, body, seen, msg):
    store, g = store_with_item(tmp_path), DraftGmail()
    with pytest.raises(actions.ActionError, match=msg):
        actions.save_draft(store, "gmail:t1", body, seen, g, "click-0001")
    assert g.drafts == []


def test_ambiguous_timeout_is_recorded_unknown_and_not_retried(tmp_path):
    import requests
    store = store_with_item(tmp_path)
    with pytest.raises(actions.ActionError, match="check Drafts"):
        actions.save_draft(store, "gmail:t1", "ok", SEEN, DraftGmail(exc=requests.Timeout()),
                           "click-0001")
    g = DraftGmail()
    with pytest.raises(actions.ActionError, match="may have gone through"):
        actions.save_draft(store, "gmail:t1", "ok", SEEN, g, "click-0001")
    assert g.drafts == []


def test_draft_account_mismatch_refused(tmp_path):
    g = DraftGmail(owner="other@example.com")
    with pytest.raises(actions.ActionError, match="actions token is for"):
        actions.save_draft(store_with_item(tmp_path), "gmail:t1", "ok", SEEN, g, "click-0001")
    assert g.drafts == []


def test_relabel_overrides_ranking_until_a_new_message(tmp_path):
    from frontdesk import evaluate
    from frontdesk.items import Triage
    store = store_with_item(tmp_path)
    store.save_triage(Triage("gmail:t1", "ignore", 1, "promo", "", "fake:m", "t",
                             "2026-10-28T16:00:00Z", prompt_version="v1"))
    actions.relabel(store, "gmail:t1", "fyi")
    t = store.ranked()[0][1]
    assert (t.bucket, t.model_bucket) == ("fyi", "ignore")
    rep = evaluate.mine_report(store)
    assert "Your corrections: 1" in rep and "ignore -> fyi: 1" in rep
    assert "promo" not in rep and "gmail:t1" not in rep          # aggregate only
    store.upsert_item(store.get_item("gmail:t1").__class__(**{
        **store.get_item("gmail:t1").__dict__, "updated_at": "2026-10-28T18:00:00Z"}))
    assert store.ranked()[0][1].bucket == "ignore"               # correction was for the old state


def test_relabel_rejects_unknown_bucket(tmp_path):
    with pytest.raises(actions.ActionError):
        actions.relabel(store_with_item(tmp_path), "gmail:t1", "urgent")


def test_done_hides_until_a_new_message(tmp_path):
    store = store_with_item(tmp_path)
    actions.set_done(store, "gmail:t1", True)
    assert store.ranked() == [] and store.is_hidden("gmail:t1")
    item = store.get_item("gmail:t1")
    item.updated_at = "2026-10-28T19:00:00Z"
    store.upsert_item(item)
    assert [i.id for i, _ in store.ranked()] == ["gmail:t1"]      # back by itself
    actions.set_done(store, "gmail:t1", True)
    actions.set_done(store, "gmail:t1", False)                     # undo
    assert [i.id for i, _ in store.ranked()] == ["gmail:t1"]


def test_archive_stays_hidden_even_if_the_thread_moves(tmp_path):
    store = store_with_item(tmp_path)
    actions.set_archived(store, "gmail:t1", True, None, "click-0001")
    item = store.get_item("gmail:t1")
    item.updated_at = "2026-10-28T19:00:00Z"
    store.upsert_item(item)
    assert store.ranked() == []          # archived threads leave on the next sync, not here


def test_mark_read_gmail_removes_unread_everywhere(tmp_path):
    store = store_with_item(tmp_path)
    item = store.get_item("gmail:t1")
    item.labels = ["INBOX", "UNREAD"]
    item.messages[0].html = "<p>keep me</p>"
    store.upsert_item(item)
    g = FakeGmail()
    assert actions.mark_read(store, "gmail:t1", g, None)["status"] == "done"
    assert g.calls == [("t1", (), ("UNREAD",))]
    assert "UNREAD" not in store.get_item("gmail:t1").labels
    assert store.message_html("gmail:t1", 0) == "<p>keep me</p>"     # labels-only update
    assert actions.mark_read(store, "gmail:t1", g, None)["status"] == "already_read"
    assert len(g.calls) == 1


class FakeSlackMark:
    def __init__(self):
        self.marked = []

    def mark(self, channel, ts):
        self.marked.append((channel, ts))


def _slack_item(store, item_id, url):
    store.upsert_item(Item(id=item_id, source="slack", account="example-team.slack.com",
                           subject="s", participants=[], updated_at="2026-10-28T16:00:00Z",
                           labels=["slack", "dm", "UNREAD"], url=url,
                           messages=[Message("Ann", "2026-10-28T16:00:00Z", "hi")]))


def test_mark_read_slack_dm_moves_read_position_to_newest(tmp_path):
    store = Store(tmp_path / "sr.db")
    _slack_item(store, "slack:D9:dm",
                "https://example-team.slack.com/archives/D9/p1730000000000100")
    sl = FakeSlackMark()
    assert actions.mark_read(store, "slack:D9:dm", None, sl)["status"] == "done"
    assert sl.marked == [("D9", "1730000000.000100")]
    assert "UNREAD" not in store.get_item("slack:D9:dm").labels


def test_mark_read_on_a_slack_channel_thread_is_here_only(tmp_path):
    # Never told to Slack (no public API moves a thread's read position, and marking the whole
    # channel would hide other unread messages); kept read here through syncs instead.
    store = Store(tmp_path / "sc.db")
    _slack_item(store, "slack:C1:1730000000.000001",
                "https://example-team.slack.com/archives/C1/p1730000000000001")
    sl = FakeSlackMark()
    out = actions.mark_read(store, "slack:C1:1730000000.000001", None, sl)
    assert out == {"status": "done", "here_only": True}
    assert sl.marked == []
    assert store.local_read("slack:C1:1730000000.000001") is not None
    assert "UNREAD" not in store.get_item("slack:C1:1730000000.000001").labels
