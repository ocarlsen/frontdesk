"""Star / unstar: Gmail's STARRED label through the actions token, a local flag for Slack (no
supported Slack API), the Starred view's payload, and the Gmail sync keeping archived starred
threads."""
from __future__ import annotations

import pytest

from frontdesk import actions
from frontdesk.gmail.client import GmailError
from frontdesk.gmail.normalize import thread_to_item
from frontdesk.items import Item, Message
from frontdesk.store import Store
from frontdesk.web import server


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


def gmail_item(store, n=1, labels=("INBOX",)):
    store.upsert_item(Item(id=f"gmail:t{n}", source="gmail", account="owner@example.com",
                           subject="s", participants=[], updated_at="2026-10-28T16:00:00Z",
                           labels=list(labels),
                           messages=[Message("a@example.com", "2026-10-28T16:00:00Z", "hi")]))


def slack_item(store):
    store.upsert_item(Item(id="slack:C1:1.0", source="slack", account="example.slack.com",
                           subject="#gen: hi", participants=[], updated_at="2026-10-28T16:00:00Z",
                           labels=["slack", "channel"],
                           messages=[Message("Ann", "2026-10-28T16:00:00Z", "hi")]))


def test_star_adds_the_label_once_per_click_and_unstar_removes_it(tmp_path):
    store, g = Store(tmp_path / "s.db"), FakeGmail()
    gmail_item(store)
    assert actions.set_starred(store, "gmail:t1", True, g, "click-0001")["status"] == "done"
    assert actions.set_starred(store, "gmail:t1", True, g, "click-0001")["status"] == "already_done"
    assert actions.set_starred(store, "gmail:t1", True, g, "click-0002")["status"] == "already_done"
    assert g.calls == [("t1", ("STARRED",), ())]
    assert "STARRED" in store.get_item("gmail:t1").labels
    assert store.action("star:gmail:t1:click-0001")["status"] == "done"     # audited
    assert actions.set_starred(store, "gmail:t1", False, g, "click-0003")["status"] == "done"
    assert g.calls[-1] == ("t1", (), ("STARRED",))
    assert store.get_item("gmail:t1").labels == ["INBOX"]


def test_star_refusals_change_nothing(tmp_path):
    store = Store(tmp_path / "r.db")
    gmail_item(store)
    with pytest.raises(actions.ActionError, match="idempotency"):
        actions.set_starred(store, "gmail:t1", True, FakeGmail(), "x")
    g = FakeGmail(owner="someone-else@example.com")
    with pytest.raises(actions.ActionError, match="actions token is for"):
        actions.set_starred(store, "gmail:t1", True, g, "click-0001")
    with pytest.raises(actions.ActionError):
        actions.set_starred(store, "gmail:t1", True, FakeGmail(fail=True), "click-0002")
    assert g.calls == [] and "STARRED" not in store.get_item("gmail:t1").labels
    assert store.action("star:gmail:t1:click-0002")["status"] == "failed"
    # a failed click retried with the same key reuses its row and succeeds
    assert actions.set_starred(store, "gmail:t1", True, FakeGmail(), "click-0002")["status"] == "done"


def test_demo_star_sends_nothing(tmp_path):
    store = Store(tmp_path / "d.db")
    gmail_item(store)
    assert actions.set_starred(store, "gmail:t1", True, None, "click-0001")["status"] == "done"
    assert store.is_starred(store.get_item("gmail:t1"))


def test_slack_star_is_local_only(tmp_path):
    store = Store(tmp_path / "sl.db")
    slack_item(store)
    out = actions.set_starred(store, "slack:C1:1.0", True, FakeGmail(), "click-0001")
    assert out == {"status": "done", "kind": "star", "starred": True, "local": True}
    item = store.get_item("slack:C1:1.0")
    assert store.is_starred(item) and "STARRED" not in item.labels
    actions.set_starred(store, "slack:C1:1.0", False, None, "click-0002")
    assert not store.is_starred(item)


def test_starred_view_payload_keeps_archived_and_done_starred_threads(tmp_path):
    store = Store(tmp_path / "p.db")
    gmail_item(store, 1, ("INBOX", "STARRED"))
    gmail_item(store, 2)
    gmail_item(store, 3, ("INBOX", "STARRED"))
    slack_item(store)
    store.set_local_star("slack:C1:1.0", True)
    actions.set_archived(store, "gmail:t1", True, None, "click-0001")
    actions.set_archived(store, "gmail:t2", True, None, "click-0002")    # not starred: gone
    actions.set_done(store, "slack:C1:1.0", True)
    rows = {r["item"]["id"]: r["item"] for r in server.ranked_payload(store)}
    assert set(rows) == {"gmail:t1", "gmail:t3", "slack:C1:1.0"}
    assert (rows["gmail:t1"]["starred"], rows["gmail:t1"]["hidden"]) == (True, "archived")
    assert (rows["slack:C1:1.0"]["starred"], rows["slack:C1:1.0"]["hidden"]) == (True, "done")
    assert (rows["gmail:t3"]["starred"], rows["gmail:t3"]["hidden"]) == (True, "")


def _post(port, body):
    import json
    import urllib.error
    import urllib.request
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/action", method="POST",
                                 data=json.dumps(body).encode(),
                                 headers={"X-FrontDesk": "action",
                                          "Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


@pytest.fixture
def served(tmp_path):
    import threading
    store = Store(tmp_path / "w.db")
    gmail_item(store)
    slack_item(store)
    started = []

    def start(settings=None):
        httpd = server.make_server(store, "127.0.0.1", 0, settings=settings)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        started.append(httpd)
        return httpd.server_address[1]
    yield store, start
    for h in started:
        h.shutdown()
        h.server_close()


def test_star_route_uses_the_actions_token(served, monkeypatch):
    from frontdesk.gmail import auth, client
    store, start = served
    g = FakeGmail()
    monkeypatch.setattr(auth, "action_credentials", lambda: "actions-creds")
    monkeypatch.setattr(client, "GmailClient", lambda creds: g if creds == "actions-creds" else None)
    port = start()
    code, out = _post(port, {"kind": "star", "item_id": "gmail:t1", "key": "k" * 16})
    assert (code, out["status"], out["kind"]) == (200, "done", "star")
    assert g.calls == [("t1", ("STARRED",), ())]
    code, out = _post(port, {"kind": "unstar", "item_id": "gmail:t1", "key": "u" * 16})
    assert code == 200 and g.calls[-1] == ("t1", (), ("STARRED",))
    assert _post(port, {"kind": "star", "item_id": "gmail:t1"})[0] == 400     # no key


def test_star_route_without_actions_token_refuses(served, monkeypatch):
    from frontdesk.gmail import auth

    def no_token():
        raise auth.AuthError("run frontdesk authorize-actions")
    monkeypatch.setattr(auth, "action_credentials", no_token)
    store, start = served
    code, out = _post(start(), {"kind": "star", "item_id": "gmail:t1", "key": "k" * 16})
    assert code == 412 and "authorize-actions" in out["error"]
    assert not store.is_starred(store.get_item("gmail:t1"))


def test_star_route_slack_and_demo_need_no_token(served, monkeypatch):
    from frontdesk.gmail import auth

    def never():
        raise AssertionError("no Gmail token for a Slack star or the demo")
    monkeypatch.setattr(auth, "action_credentials", never)
    store, start = served
    code, out = _post(start(), {"kind": "star", "item_id": "slack:C1:1.0", "key": "k" * 16})
    assert code == 200 and out["local"] is True
    code, out = _post(start({"demo": True}), {"kind": "star", "item_id": "gmail:t1",
                                              "key": "d" * 16})
    assert code == 200 and out["status"] == "done"
    assert store.is_starred(store.get_item("gmail:t1"))


def test_ask_payload_carries_the_built_in_question(tmp_path):
    from frontdesk.assist import ADVISE
    store = Store(tmp_path / "a.db")
    gmail_item(store)
    assert server.ask_payload(store, store.get_item("gmail:t1"))["advise"] == ADVISE


class SyncGmail:
    """Listing answers per query; get_thread from a dict of raw threads."""

    def __init__(self, inbox, starred, threads, fail_starred=False):
        self.inbox, self.starred, self.threads = inbox, starred, threads
        self.fail_starred = fail_starred

    def profile_email(self):
        return "owner@example.com"

    def list_thread_ids(self, query, max_threads):
        if query == "is:starred":
            if self.fail_starred:
                raise GmailError(500, "threads", "x")
            return list(self.starred)
        return list(self.inbox)

    def get_thread(self, tid):
        return self.threads[tid]


def _raw(tid, labels):
    return {"id": tid, "messages": [{
        "id": "m" + tid, "internalDate": "1793000000000", "labelIds": list(labels),
        "payload": {"mimeType": "text/plain", "body": {"data": "aGk="},
                    "headers": [{"name": "From", "value": "Ann <ann@example.com>"},
                                {"name": "To", "value": "owner@example.com"},
                                {"name": "Subject", "value": "Hi " + tid}]}}]}


def _sync(monkeypatch, store, fake):
    from frontdesk.gmail import sync as gsync
    monkeypatch.setattr(gsync, "GmailClient", lambda creds: fake)
    monkeypatch.setattr(gsync.auth, "credentials", lambda interactive=True: None)
    return gsync.sync(store, {"gmail_query": "in:inbox", "gmail_max_threads": 50},
                      log=lambda *_: None)


def test_sync_keeps_archived_starred_threads_and_unhides_returns(tmp_path, monkeypatch):
    store = Store(tmp_path / "g.db")
    threads = {t: _raw(t, ["INBOX", "STARRED"] if t != "b" else ["INBOX"]) for t in "abc"}
    _sync(monkeypatch, store, SyncGmail("abc", "ac", threads))
    for t in "abc":
        actions.set_archived(store, f"gmail:{t}", True, None, f"click-000{t}")
    # a and c archived and still starred in Gmail; b archived, not starred
    res = _sync(monkeypatch, store, SyncGmail("", "ac", threads))
    assert res.removed == 1 and store.get_item("gmail:b") is None
    assert store.hidden_reason("gmail:a") == "archived"
    ids = {r["item"]["id"]: r["item"]["hidden"] for r in server.ranked_payload(store)}
    assert ids == {"gmail:a": "archived", "gmail:c": "archived"}
    # c unstarred in Gmail: pruned. a moved back to the inbox: visible again.
    _sync(monkeypatch, store, SyncGmail("a", "a", threads))
    assert store.get_item("gmail:c") is None
    assert store.hidden_reason("gmail:a") == "" and [i.id for i, _ in store.ranked()] == ["gmail:a"]


def test_sync_keeps_archived_threads_when_the_starred_listing_fails(tmp_path, monkeypatch):
    store = Store(tmp_path / "f.db")
    threads = {"a": _raw("a", ["INBOX"])}
    _sync(monkeypatch, store, SyncGmail("a", "", threads))
    actions.set_archived(store, "gmail:a", True, None, "click-0001")
    _sync(monkeypatch, store, SyncGmail("", "", threads, fail_starred=True))
    assert store.get_item("gmail:a") is not None


def test_page_does_not_duplicate_the_built_in_question():
    from pathlib import Path

    from frontdesk.assist import ADVISE
    js = (Path(server.__file__).parent / "app.js").read_text()
    assert ADVISE[:40] not in js and "Advise me" not in js and "Ask all\"" not in js


# Gmail's listing can be stale: it has listed 2014 threads for in:inbox whose messages carry no
# INBOX label (Gmail's own inbox does not show them). Sync goes by the fetched labels.
def test_inbox_sync_leaves_out_listed_threads_without_the_inbox_label(tmp_path, monkeypatch):
    store = Store(tmp_path / "s.db")
    threads = {"a": _raw("a", ["INBOX"]), "old": _raw("old", ["IMPORTANT"]), "k": _raw("k", [])}
    store.keep(thread_to_item(threads["k"], "owner@example.com"))     # kept from a search
    stored_before = thread_to_item(threads["old"], "owner@example.com")
    store.upsert_item(stored_before)                                   # synced by an older version
    res = _sync(monkeypatch, store, SyncGmail(["a", "old", "k"], "", threads))
    assert store.get_item("gmail:a") is not None
    assert store.get_item("gmail:old") is None                         # left out, and pruned
    assert store.get_item("gmail:k") is not None                       # kept threads stay
    assert res.removed == 1


def test_a_non_inbox_query_keeps_threads_without_the_inbox_label(tmp_path, monkeypatch):
    from frontdesk.gmail import sync as gsync
    store = Store(tmp_path / "s.db")
    threads = {"w": _raw("w", ["Label_7"])}
    monkeypatch.setattr(gsync, "GmailClient", lambda creds: SyncGmail(["w"], "", threads))
    monkeypatch.setattr(gsync.auth, "credentials", lambda interactive=True: None)
    gsync.sync(store, {"gmail_query": "label:work newer_than:7d", "gmail_max_threads": 50},
               log=lambda *_: None)
    assert store.get_item("gmail:w") is not None
