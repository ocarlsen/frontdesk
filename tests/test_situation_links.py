"""What's going on items linked to a thread close themselves (a reply from someone else, or the
thread marked done or archived in FrontDesk), can be reopened, and session items not restated
for a week go stale: ranking leaves both out, Ask leaves closed ones out."""
from __future__ import annotations

import io
import sqlite3

import pytest

from frontdesk import __main__ as cli
from frontdesk import actions, assist, triage
from frontdesk.items import Item, Message
from frontdesk.store import InvalidMemory, Store

T0 = "2026-11-01T10:00:00Z"


def thread(n=1, *msgs):
    msgs = msgs or (("Bo <bo@example.com>", T0, False),)
    ms = [Message(who, at, "body", is_mine=mine) for who, at, mine in msgs]
    return Item(id=f"gmail:t{n}", source="gmail", account="owner@example.com",
                subject=f"Quote {n}", participants=["bo@example.com", "owner@example.com"],
                messages=ms, updated_at=max(m.sent_at for m in ms))


def linked(s, n=1, author="session:a", text="Waiting on Bo's revised quote."):
    s.upsert_item(thread(n))
    return s.add_situation(text, author, f"gmail:t{n}")


def row(s, i):
    return next(r for r in s.situation() if r["id"] == i)


def test_a_reply_from_someone_else_closes_it_and_the_owners_own_does_not(tmp_path):
    s = Store(tmp_path / "s.db")
    i = linked(s)
    s.upsert_item(thread(1, ("Bo <bo@example.com>", T0, False),
                         ("Me <owner@example.com>", "2026-11-02T09:00:00Z", True)))
    assert row(s, i)["closed_at"] == ""                      # my nudge does not resolve it
    s.upsert_item(thread(1, ("Bo <bo@example.com>", T0, False),
                         ("Me <owner@example.com>", "2026-11-02T09:00:00Z", True),
                         ("Bo <bo@example.com>", "2026-11-03T09:00:00Z", False)))
    r = row(s, i)
    assert r["closed_reason"] == "reply" and r["closed_at"]
    assert [x["id"] for x in s.situation(open_only=True)] == []


def test_done_closes_and_undo_reopens(tmp_path):
    s = Store(tmp_path / "s.db")
    i = linked(s)
    s.hide("gmail:t1", "done", T0)
    assert row(s, i)["closed_reason"] == "done"
    s.unhide("gmail:t1")
    assert row(s, i)["closed_at"] == ""


def test_archive_closure_survives_prune_and_aged_out_threads_stay_open(tmp_path):
    s = Store(tmp_path / "s.db")
    a = linked(s, 1)
    b = linked(s, 2, text="Waiting on Dee.")
    s.hide("gmail:t1", "archived")
    assert s.prune("gmail", "owner@example.com", set()) == 2   # both threads leave the store
    assert row(s, a)["closed_reason"] == "archived"
    # t2 just aged out of the sync window: nothing says it was resolved, so it stays open,
    # marked as no longer able to close by itself
    rb = row(s, b)
    assert rb["closed_at"] == "" and rb["thread_gone"] is True


def test_prune_closes_an_item_linked_after_its_thread_was_archived(tmp_path):
    # hide() closes items linked at that moment; one linked later is closed by prune, which
    # runs while the thread's archived state still exists
    s = Store(tmp_path / "s.db")
    s.upsert_item(thread(1))
    s.hide("gmail:t1", "archived")
    i = s.add_situation("Waiting on Bo.", "session:a", "gmail:t1")
    assert row(s, i)["closed_at"] == ""
    s.prune("gmail", "owner@example.com", set())
    assert row(s, i)["closed_reason"] == "archived"


def test_reopen_waits_for_a_new_reply(tmp_path):
    s = Store(tmp_path / "s.db")
    i = linked(s)
    second = thread(1, ("Bo <bo@example.com>", T0, False),
                    ("Bo <bo@example.com>", "2026-11-02T09:00:00Z", False))
    s.upsert_item(second)
    assert row(s, i)["closed_reason"] == "reply"
    s.reopen_situation(i)
    assert row(s, i)["closed_at"] == ""
    s.upsert_item(second)                                   # the same reply again: no re-close
    assert row(s, i)["closed_at"] == ""
    s.upsert_item(thread(1, ("Bo <bo@example.com>", T0, False),
                         ("Bo <bo@example.com>", "2026-11-02T09:00:00Z", False),
                         ("Bo <bo@example.com>", "2026-11-04T09:00:00Z", False)))
    assert row(s, i)["closed_reason"] == "reply"
    with pytest.raises(InvalidMemory):
        s.reopen_situation(9999)


def test_unknown_thread_is_refused(tmp_path):
    s = Store(tmp_path / "s.db")
    with pytest.raises(InvalidMemory, match="no stored thread"):
        s.add_situation("x", "session:a", "gmail:nope")
    with pytest.raises(InvalidMemory, match="no stored thread"):
        s.sync_situation("session:a", [("x", "gmail:nope")])
    assert s.situation() == []


def test_sync_links_new_items_and_keeps_existing_state(tmp_path):
    s = Store(tmp_path / "s.db")
    s.upsert_item(thread(1))
    assert s.sync_situation("session:a", [("Waiting on Bo.", "gmail:t1"), "Plain item."]) \
        == (0, 2, 0)
    by = {r["text"]: r for r in s.situation()}
    assert by["Waiting on Bo."]["thread_id"] == "gmail:t1" and by["Plain item."]["thread_id"] == ""
    s.hide("gmail:t1", "done", T0)
    # restating a closed item keeps it closed; the session sees that in `situation list`
    assert s.sync_situation("session:a", ["Waiting on Bo.", "Plain item."]) == (2, 0, 0)
    assert {r["text"]: r["closed_reason"] for r in s.situation()}["Waiting on Bo."] == "done"


def test_stale_is_for_unrestated_session_items_only(tmp_path):
    s = Store(tmp_path / "s.db")
    old = "2026-01-01T00:00:00Z"
    sess = s.add_situation("Session item.", "session:a")
    mine = s.add_situation("My item.", "owner")
    closed = linked(s, text="Closed item.")
    s.hide("gmail:t1", "done", T0)
    s.db.execute("UPDATE situation SET updated_at=?", (old,))
    s.db.commit()
    assert row(s, sess)["stale"] is True
    assert row(s, mine)["stale"] is False and row(s, closed)["stale"] is False
    s.sync_situation("session:a", ["Session item.", "Closed item."])   # restating refreshes it
    assert row(s, sess)["stale"] is False


def test_ranking_leaves_out_closed_and_stale_and_ask_leaves_out_closed(tmp_path):
    s = Store(tmp_path / "s.db")
    s.add_situation("Open item.", "owner")
    stale = s.add_situation("Stale item.", "session:a")
    linked(s, text="Closed item.")
    s.hide("gmail:t1", "done", T0)
    s.db.execute("UPDATE situation SET updated_at=? WHERE id=?", ("2026-01-01T00:00:00Z", stale))
    s.db.commit()
    block = triage.situation_block(s.situation())
    assert "Open item." in block and "Stale item." not in block and "Closed item." not in block
    s.upsert_item(thread(2))
    p = assist.build_prompt(s, s.get_item("gmail:t2"), "?", "", author="owner")
    assert "Open item." in p and "Stale item." in p and "Closed item." not in p


def test_reopen_action_needs_an_author(tmp_path):
    s = Store(tmp_path / "s.db")
    i = linked(s)
    s.hide("gmail:t1", "done", T0)
    with pytest.raises(actions.ActionError):
        actions.situation_reopen(s, i, None)
    assert actions.situation_reopen(s, i, "owner") == {"status": "done"}
    assert row(s, i)["closed_at"] == ""


def test_old_database_gains_the_link_columns(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE situation (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT "
                "NULL, author TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    con.execute("INSERT INTO situation (text, author, created_at, updated_at) VALUES "
                "('Old item.', 'owner', ?, ?)", (T0, T0))
    con.commit()
    con.close()
    r = Store(db).situation()[0]
    assert r["text"] == "Old item." and r["thread_id"] == "" and r["closed_at"] == ""


def test_cli_links_threads_and_lists_state(capsys, monkeypatch):
    s = Store()
    s.upsert_item(thread(1))
    assert cli.main(["situation", "add", "Waiting on Bo.", "--by", "a",
                     "--thread", "gmail:t1"]) == 0
    assert cli.main(["situation", "add", "x", "--by", "a", "--thread", "gmail:nope"]) == 2
    monkeypatch.setattr("sys.stdin", io.StringIO("thread:gmail:t1 Waiting on Bo.\nOther.\n"))
    assert cli.main(["situation", "sync", "--by", "b"]) == 0
    capsys.readouterr()
    s.hide("gmail:t1", "done", T0)
    assert cli.main(["situation", "list"]) == 0
    out = capsys.readouterr().out
    assert "[closed: done" in out and "[thread:gmail:t1]" in out
    # session b's identical text was not duplicated; its plain item was added
    assert [r["text"] for r in Store().situation()] == ["Waiting on Bo.", "Other."]
