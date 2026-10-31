"""The usage log: one row per ranking, Ask answer, saved draft, real send, search and keep; counts
and costs only, never mail; whether a reply went out as FrontDesk wrote it; `frontdesk stats`."""
from __future__ import annotations

import json
import sqlite3
from datetime import timedelta

from test_actions import DraftGmail
from test_sending import SEEN, T0, FakeGmail, prepared
from test_sending import store as send_store

from frontdesk import actions, sending, stats
from frontdesk import store as store_mod
from frontdesk.store import Store
from frontdesk.triage import Triage
from frontdesk.usage import origin_of

SECRET = "Lunch Thursday?"   # mail text that must never reach the usage table


def rows(s: Store) -> list[dict]:
    return [dict(r) for r in s.db.execute("SELECT * FROM usage ORDER BY id")]


def tri(proposed: str = "Thursday works.", cost: float = 0.0146) -> Triage:
    return Triage("gmail:t1", "needs_you", 3, "Ann asks about lunch", proposed, "anthropic:x",
                  "2026-10-28T16:01:00Z", SEEN, "v1", "claude-opus-5-5", 1000, 200, 0, 0, 900,
                  cost, "Ann asks.")


def test_ranking_and_ask_answers_are_logged_with_model_and_cost(tmp_path):
    s = send_store(tmp_path)
    s.save_triage(tri())
    s.add_ask("gmail:t1", "owner", "What now?", "owner")
    s.add_ask("gmail:t1", "assistant", "Say yes.", "owner", {"model": "claude-opus-5-5", "cost_usd": 0.03})
    r = rows(s)
    assert [(x["kind"], x["source"], x["model"]) for x in r] == [
        ("rank", "gmail", "claude-opus-5-5"), ("ask", "gmail", "claude-opus-5-5")]
    assert r[0]["cost_usd"] == 0.0146 and r[0]["tokens_in"] == 1000 and r[1]["cost_usd"] == 0.03


def test_origins(tmp_path):
    s = send_store(tmp_path)
    item = s.get_item("gmail:t1")
    assert origin_of(s, item, "Anything.", signoff="") == "written"
    s.save_triage(tri("Thursday works."))
    assert origin_of(s, item, "Thursday  works.\n", signoff="Best,\nAlex") == "proposed"
    assert origin_of(s, item, "Thursday works.\n\nBest,\nAlex", signoff="Best,\nAlex") == "proposed"
    assert origin_of(s, item, "Friday works.", signoff="") == "edited"
    s.add_ask("gmail:t1", "assistant", "x", "owner", {"draft_reply": "Friday at noon?"})
    assert origin_of(s, item, "Friday at noon?", signoff="") == "ask_draft"


def test_a_saved_draft_and_a_real_send_are_logged_once_with_their_origin(tmp_path, monkeypatch):
    monkeypatch.setattr("frontdesk.usage._signoff", lambda: "")
    s = send_store(tmp_path)
    s.save_triage(tri("Thursday works."))
    actions.save_draft(s, "gmail:t1", "Thursday works.", SEEN, DraftGmail(), "click-0009")
    g = FakeGmail()
    p = prepared(s, g, body="Thursday works, see you.")
    sending.confirm(s, p["action_id"], now=T0)
    sending.dispatch_due(s, lambda: g, now=T0 + timedelta(seconds=31))
    sending.dispatch_due(s, lambda: g, now=T0 + timedelta(seconds=60))   # nothing more to send
    kinds = [(x["kind"], x["origin"]) for x in rows(s) if x["kind"] in ("draft", "send")]
    assert kinds == [("draft", "proposed"), ("send", "edited")]


def test_a_cancelled_send_is_not_counted(tmp_path, monkeypatch):
    monkeypatch.setattr("frontdesk.usage._signoff", lambda: "")
    s, g = send_store(tmp_path), FakeGmail()
    p = prepared(s, g)
    sending.confirm(s, p["action_id"], now=T0)
    sending.cancel(s, p["action_id"])
    sending.dispatch_due(s, lambda: g, now=T0 + timedelta(seconds=31))
    assert not [x for x in rows(s) if x["kind"] == "send"]


def test_the_log_never_holds_mail_text(tmp_path, monkeypatch):
    monkeypatch.setattr("frontdesk.usage._signoff", lambda: "")
    s = send_store(tmp_path)
    s.save_triage(tri(SECRET))
    actions.save_draft(s, "gmail:t1", SECRET, SEEN, DraftGmail(), "click-0010")
    dump = json.dumps(rows(s))
    assert SECRET not in dump and "gmail:t1" not in dump and "ann@example.com" not in dump


def test_backfill_seeds_existing_rankings_and_answers_once(tmp_path):
    s = send_store(tmp_path)   # a fresh store has already backfilled (nothing); simulate an old one
    s.save_triage(tri())
    s.add_ask("gmail:t1", "assistant", "Yes.", "owner", {"model": "m", "cost_usd": 0.02})
    s.db.close()
    con = sqlite3.connect(tmp_path / "s.db")
    con.execute("DELETE FROM usage")
    con.execute("DELETE FROM meta WHERE key=?", (store_mod.USAGE_MARKER,))
    con.commit()
    con.close()
    s2 = Store(tmp_path / "s.db")
    assert sorted(x["kind"] for x in rows(s2)) == ["ask", "rank"]
    s2.db.close()
    assert len(rows(Store(tmp_path / "s.db"))) == 2          # a second open adds nothing


def test_stats_render():
    assert "No usage logged yet" in stats.render({"since": "", "first": "", "kinds": {}})
    out = stats.render({"since": "", "first": "2026-10-28T16:00:00Z", "kinds": {
        "rank": {"n": 4, "cost_usd": 0.06, "models": {"claude-opus-5-5": {"n": 4, "cost_usd": 0.06}},
                 "origins": {}},
        "send": {"n": 4, "cost_usd": 0.0, "models": {}, "origins": {"proposed": 3, "edited": 1}}}})
    assert "since 2026-10-28" in out and "1.50¢ each" in out
    assert "3 as FrontDesk proposed (75%)" in out and "1 edited (25%)" in out
    assert "$0.06 paid to your provider" in out


def test_stats_summary_window(tmp_path):
    s = send_store(tmp_path)
    s.save_triage(tri())
    s.db.execute("UPDATE usage SET at='2020-01-01T00:00:00Z'")
    s.db.commit()
    s.log_usage("search", source="gmail")
    assert set(s.usage_summary("2026-01-01T00:00:00Z")["kinds"]) == {"search"}
    assert set(s.usage_summary()["kinds"]) == {"rank", "search"}
