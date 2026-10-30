"""GET /api/gmail-draft: the thread's draft comes from Gmail on each open; nothing is stored."""
from __future__ import annotations

import base64
from http import HTTPStatus

import requests
from test_actions import store_with_item

from frontdesk.gmail.auth import AuthError
from frontdesk.gmail.client import GmailError
from frontdesk.web.server import gmail_draft


def _thread(*drafts):
    msgs = [{"id": "m1", "internalDate": "1000", "labelIds": ["INBOX"],
             "payload": {"mimeType": "text/plain", "headers": [],
                         "body": {"data": base64.urlsafe_b64encode(b"Lunch?").decode()}}}]
    for i, text in enumerate(drafts):
        msgs.append({"id": f"dm{i}", "internalDate": str(2000 + i), "labelIds": ["DRAFT"],
                     "payload": {"mimeType": "text/plain", "headers": [],
                                 "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()}}})
    return {"id": "t1", "messages": msgs}


class G:
    def __init__(self, thread=None, exc=None):
        self.thread, self.exc, self.asked = thread, exc, []

    def get_thread(self, tid):
        self.asked.append(tid)
        if self.exc:
            raise self.exc
        return self.thread


def _db(tmp_path):
    store = store_with_item(tmp_path)
    path = store.path
    store.db.close()
    return path


def test_returns_gmails_current_draft_text(tmp_path):
    db = _db(tmp_path)
    g = G(_thread("Saved from FrontDesk.", "Then edited in Gmail."))
    code, out = gmail_draft(db, {}, "gmail:t1", client_factory=lambda: g)
    assert code == HTTPStatus.OK and g.asked == ["t1"]
    assert out["draft"]["body"] == "Then edited in Gmail."
    assert "#drafts?compose=dm1" in out["draft"]["url"]


def test_no_draft_demo_and_slack_return_none_without_asking_gmail(tmp_path):
    db = _db(tmp_path)
    assert gmail_draft(db, {}, "gmail:t1", client_factory=lambda: G(_thread()))[1] == {"draft": None}
    g = G(_thread("x"))
    assert gmail_draft(db, {"demo": True}, "gmail:t1", client_factory=lambda: g)[1] == {"draft": None}
    assert gmail_draft(db, {}, "slack:C1:1", client_factory=lambda: g)[1] == {"draft": None}
    assert g.asked == []


def test_failures_are_loud_and_never_echo_gmails_error_text(tmp_path):
    db = _db(tmp_path)
    code, out = gmail_draft(db, {}, "gmail:t1",
                            client_factory=lambda: G(exc=GmailError(500, "threads/t1", "<secret body>")))
    assert code == HTTPStatus.BAD_GATEWAY and out == {"error": "Gmail did not answer"}
    code, out = gmail_draft(db, {}, "gmail:t1",
                            client_factory=lambda: G(exc=requests.ConnectionError("x")))
    assert code == HTTPStatus.BAD_GATEWAY
    code, out = gmail_draft(db, {}, "gmail:t1",
                            client_factory=lambda: G(exc=AuthError("Gmail sign-in needed.")))
    assert code == HTTPStatus.BAD_GATEWAY and "sign-in" in out["error"]
    assert gmail_draft(db, {}, "gmail:nope", client_factory=lambda: G())[0] == HTTPStatus.NOT_FOUND
