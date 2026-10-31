"""Actions on a Gmail search result FrontDesk has not stored: one label change on the thread in
Gmail, by thread id, nothing stored, and refused for anything but a Gmail thread id."""
from __future__ import annotations

import pytest
from test_move_to_inbox import ModGmail

from frontdesk import actions
from frontdesk.store import Store
from frontdesk.web import server

TID = "18c0ffee00000001"


@pytest.mark.parametrize("op,add,remove", [
    ("inbox", ["INBOX"], []), ("archive", [], ["INBOX"]), ("read", [], ["UNREAD"]),
    ("unread", ["UNREAD"], []), ("star", ["STARRED"], []), ("unstar", [], ["STARRED"])])
def test_each_op_is_one_label_change(op, add, remove):
    g = ModGmail()
    assert actions.result_op(f"gmail:{TID}", op, g)["status"] == "done"
    assert g.mods == [(TID, add, remove)]


def test_each_op_has_its_reverse():
    # The bar's Undo sends the reverse op, so every op must have one.
    flip = {"inbox": "archive", "read": "unread", "star": "unstar"}
    flip.update({v: k for k, v in flip.items()})
    for op, (add, remove) in actions.RESULT_OPS.items():
        assert actions.RESULT_OPS[flip[op]] == (remove, add)


@pytest.mark.parametrize("item_id,op", [
    ("slack:C1:1.2", "read"), ("gmail:../x", "read"), ("gmail:" + TID, "trash"),
    ("gmail:" + TID, "send"), ("", "read")])
def test_refuses_other_ids_and_ops(item_id, op):
    g = ModGmail()
    with pytest.raises(actions.ActionError):
        actions.result_op(item_id, op, g)
    assert g.mods == []


def test_route_stores_nothing_and_is_a_no_op_in_demo(tmp_path):
    db = tmp_path / "s.db"
    Store(db).db.close()
    code, out = server.run_action(db, {"demo": True},
                                  {"kind": "result", "item_id": f"gmail:{TID}", "op": "archive"})
    assert code == 200 and out == {"status": "done", "demo": True, "op": "archive"}
    s = Store(db)
    assert s.get_item(f"gmail:{TID}") is None and s.kept_ids() == set()


def test_route_refuses_a_bad_op(tmp_path):
    db = tmp_path / "s.db"
    Store(db).db.close()
    code, _ = server.run_action(db, {"demo": True},
                                {"kind": "result", "item_id": f"gmail:{TID}", "op": "delete"})
    assert code == 409
    code, _ = server.run_action(db, {"demo": True}, {"kind": "result", "item_id": f"gmail:{TID}"})
    assert code == 400


def test_search_rows_carry_starred():
    from frontdesk.gmail.search import thread_row
    t = {"id": TID, "messages": [{"labelIds": ["STARRED", "INBOX"], "internalDate": "1",
                                  "payload": {"headers": [{"name": "Subject", "value": "s"},
                                                          {"name": "From", "value": "a@b.c"}]}}]}
    assert thread_row(t, "owner@example.com")["starred"] is True
