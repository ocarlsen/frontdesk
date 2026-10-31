"""Keep from search: a result read in place stores nothing; Keep stores it, ranks it once, and
sync keeps it current until it is archived or marked done."""
from __future__ import annotations

from http import HTTPStatus

from test_star import SyncGmail, _raw, _sync

from frontdesk import actions
from frontdesk.providers import Completion, ProviderError
from frontdesk.store import Store
from frontdesk.web import server

OLD = "abc123"          # an archived thread, outside the sync query


class Provider:
    name, model = "fake", "claude-opus-5-5"

    def __init__(self, fail=False):
        self.fail, self.calls = fail, 0

    def complete_json(self, system, user, schema, max_tokens=2048):
        self.calls += 1
        if self.fail:
            raise ProviderError("overloaded")
        return Completion({"bucket": "needs_you", "urgency": 3, "reason": "Old thread, open ask.",
                           "proposed_reply": "Hi Ann,\n\nYes.", "summary": "Ann asked; no answer yet."})


def threads():
    return {OLD: _raw(OLD, ["CATEGORY_PERSONAL"]), "def456": _raw("def456", ["INBOX"])}


def test_preview_reads_the_thread_and_stores_nothing(tmp_path):
    db = tmp_path / "a.db"
    Store(db).db.close()
    code, out = server.search_thread({}, f"gmail:{OLD}", client_factory=lambda: SyncGmail("", "", threads()))
    assert code == HTTPStatus.OK and out["item"]["id"] == f"gmail:{OLD}"
    assert all(m["has_html"] is False and "html" not in m for m in out["item"]["messages"])
    assert Store(db).get_item(f"gmail:{OLD}") is None


def test_bad_ids_and_demo_never_reach_gmail():
    for bad in ("", "slack:C1:1", "gmail:../x", "gmail:ZZZZZZ"):
        assert server.search_thread({}, bad, client_factory=lambda: 1 / 0)[0] == HTTPStatus.BAD_REQUEST
    assert server.search_thread({"demo": True}, f"gmail:{OLD}", client_factory=lambda: 1 / 0)[0] \
        == HTTPStatus.CONFLICT


def test_keep_stores_ranks_once_and_lists_it_as_kept(tmp_path):
    db = tmp_path / "a.db"
    p = Provider()
    code, out = server.keep_result(db, {}, f"gmail:{OLD}",
                                   client_factory=lambda: SyncGmail("", "", threads()),
                                   provider_factory=lambda: p)
    assert code == HTTPStatus.OK and out["ranked"] and p.calls == 1
    s = Store(db)
    assert s.is_kept(f"gmail:{OLD}") and s.kept_ids() == {f"gmail:{OLD}"}
    row = next(r for r in server.ranked_payload(s) if r["item"]["id"] == f"gmail:{OLD}")
    assert row["item"]["kept"] and row["triage"]["bucket"] == "needs_you"


def test_keep_survives_a_ranking_failure(tmp_path):
    db = tmp_path / "a.db"
    code, out = server.keep_result(db, {}, f"gmail:{OLD}",
                                   client_factory=lambda: SyncGmail("", "", threads()),
                                   provider_factory=lambda: Provider(fail=True))
    assert code == HTTPStatus.OK and out["ranked"] is False and Store(db).is_kept(f"gmail:{OLD}")


def test_sync_keeps_a_kept_thread_until_it_is_archived(tmp_path, monkeypatch):
    s = Store(tmp_path / "g.db")
    server.keep_result(s.path, {}, f"gmail:{OLD}", client_factory=lambda: SyncGmail("", "", threads()),
                       provider_factory=Provider)
    fake = SyncGmail("def456", "", threads())
    fetched = []
    orig = fake.get_thread
    fake.get_thread = lambda tid: (fetched.append(tid), orig(tid))[1]
    res = _sync(monkeypatch, s, fake)
    assert OLD in fetched and res.removed == 0 and s.get_item(f"gmail:{OLD}") is not None
    actions.set_archived(s, f"gmail:{OLD}", True, None, "click-0001")
    res = _sync(monkeypatch, s, SyncGmail("def456", "", threads()))
    assert res.removed == 1 and s.get_item(f"gmail:{OLD}") is None and not s.is_kept(f"gmail:{OLD}")
