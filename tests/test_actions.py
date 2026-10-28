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
