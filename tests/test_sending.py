"""Send: derived recipients, confirm then undo window, cancel, stale and expiry, no retry."""
from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import pytest
import requests

from frontdesk import sending
from frontdesk.actions import ActionError
from frontdesk.gmail.client import GmailError
from frontdesk.items import Item, Message
from frontdesk.store import Store

SEEN = "2026-10-28T16:00:00Z"
T0 = datetime(2026, 10, 28, 17, 0, tzinfo=UTC)


class FakeGmail:
    def __init__(self, exc=None, owner="owner@example.com"):
        self.exc, self.owner, self.sent = exc, owner, []

    def profile_email(self):
        return self.owner

    def get_thread(self, tid):
        return {"id": tid, "messages": [{
            "id": "m1", "internalDate": "1000", "labelIds": ["INBOX"],
            "payload": {"headers": [{"name": "From", "value": "Ann <ann@example.com>"},
                                    {"name": "Subject", "value": "Lunch"},
                                    {"name": "Message-ID", "value": "<m1@x>"}]}}]}

    def send_message(self, raw, thread_id=None):
        if self.exc:
            raise self.exc
        self.sent.append((raw, thread_id))
        return {"id": "g1"}


def store(tmp_path):
    s = Store(tmp_path / "s.db")
    s.upsert_item(Item(id="gmail:t1", source="gmail", account="owner@example.com",
                       subject="Lunch", participants=[], updated_at=SEEN,
                       messages=[Message("Ann <ann@example.com>", SEEN, "Lunch Thursday?")]))
    return s


def prepared(s, g, body="Thursday works.", key="click-0001"):
    return sending.prepare(s, "gmail:t1", body, SEEN, g, key, now=T0)


def test_full_flow_sends_once_after_the_undo_window(tmp_path):
    s, g = store(tmp_path), FakeGmail()
    p = prepared(s, g)
    assert p["to"] == ["ann@example.com"] and p["subject"] == "Re: Lunch"
    c = sending.confirm(s, p["action_id"], now=T0)
    assert c["send_at"] == "2026-10-28T17:00:30Z"
    assert sending.dispatch_due(s, lambda: g, now=T0 + timedelta(seconds=10)) == []
    assert g.sent == []                                   # still inside the undo window
    assert sending.dispatch_due(s, lambda: g, now=T0 + timedelta(seconds=31)) == \
        [(p["action_id"], "sent")]
    assert sending.dispatch_due(s, lambda: g, now=T0 + timedelta(seconds=60)) == []
    raw, tid = g.sent[0]
    assert tid == "t1" and b"In-Reply-To: <m1@x>" in base64.urlsafe_b64decode(raw)
    assert b"Thursday works." in base64.urlsafe_b64decode(raw)


def test_cancel_inside_window_and_not_after(tmp_path):
    s, g = store(tmp_path), FakeGmail()
    p = prepared(s, g)
    sending.confirm(s, p["action_id"], now=T0)
    assert sending.cancel(s, p["action_id"])["status"] == "cancelled"
    assert sending.dispatch_due(s, lambda: g, now=T0 + timedelta(minutes=1)) == []
    assert g.sent == []
    p2 = prepared(s, g, key="click-0002")
    sending.confirm(s, p2["action_id"], now=T0)
    sending.dispatch_due(s, lambda: g, now=T0 + timedelta(seconds=31))
    with pytest.raises(ActionError, match="too late"):
        sending.cancel(s, p2["action_id"])


def test_new_message_after_confirm_stops_the_send(tmp_path):
    s, g = store(tmp_path), FakeGmail()
    p = prepared(s, g)
    sending.confirm(s, p["action_id"], now=T0)
    item = s.get_item("gmail:t1")
    item.updated_at = "2026-10-28T17:00:10Z"
    s.upsert_item(item)
    assert sending.dispatch_due(s, lambda: g, now=T0 + timedelta(seconds=31)) == \
        [(p["action_id"], "stale")]
    assert g.sent == []


def test_server_down_past_due_expires_instead_of_sending(tmp_path):
    s, g = store(tmp_path), FakeGmail()
    p = prepared(s, g)
    sending.confirm(s, p["action_id"], now=T0)
    assert sending.dispatch_due(s, lambda: g, now=T0 + timedelta(hours=2)) == \
        [(p["action_id"], "expired")]
    assert g.sent == []


def test_timeout_is_unknown_and_never_retried(tmp_path):
    s = store(tmp_path)
    p = prepared(s, FakeGmail())
    sending.confirm(s, p["action_id"], now=T0)
    flaky = FakeGmail(exc=requests.Timeout())
    assert sending.dispatch_due(s, lambda: flaky, now=T0 + timedelta(seconds=31)) == \
        [(p["action_id"], "unknown")]
    ok = FakeGmail()
    assert sending.dispatch_due(s, lambda: ok, now=T0 + timedelta(seconds=40)) == []
    assert ok.sent == []


def test_gmail_error_is_failed(tmp_path):
    s = store(tmp_path)
    p = prepared(s, FakeGmail())
    sending.confirm(s, p["action_id"], now=T0)
    bad = FakeGmail(exc=GmailError(400, "messages/send", "bad"))
    assert sending.dispatch_due(s, lambda: bad, now=T0 + timedelta(seconds=31)) == \
        [(p["action_id"], "failed")]


@pytest.mark.parametrize("body,seen,msg", [
    ("", SEEN, "empty"),
    ("See you at [time].", SEEN, "bracketed"),
    ("ok", "2026-10-28T18:00:00Z", "new message arrived"),
])
def test_prepare_refusals(tmp_path, body, seen, msg):
    with pytest.raises(ActionError, match=msg):
        sending.prepare(store(tmp_path), "gmail:t1", body, seen, FakeGmail(), "click-0001",
                        now=T0)


def test_rate_limits(tmp_path):
    s, g = store(tmp_path), FakeGmail()
    p = prepared(s, g)
    sending.confirm(s, p["action_id"], now=T0)
    with pytest.raises(ActionError, match="last 10 minutes"):
        sending.prepare(s, "gmail:t1", "again", SEEN, g, "click-0002",
                        now=datetime.now(UTC))


def test_account_mismatch_refused(tmp_path):
    with pytest.raises(ActionError, match="actions token is for"):
        prepared(store(tmp_path), FakeGmail(owner="other@example.com"))


def test_demo_mode_never_sends(tmp_path):
    s = store(tmp_path)
    p = sending.prepare(s, "gmail:t1", "ok", SEEN, None, "click-0001", now=T0)
    assert p["demo"] and p["to"] == ["ann@example.com"]
    c = sending.confirm(s, p["action_id"], now=T0)
    assert c["demo"]
    assert sending.dispatch_due(s, lambda: pytest.fail("demo must not dispatch"),
                                now=T0 + timedelta(minutes=1)) == []


def test_only_the_send_module_can_send():
    """The privacy page promises mail leaves only through the confirm-and-undo flow."""
    import pathlib
    import re
    pkg = pathlib.Path(sending.__file__).parent
    callers = sorted(str(p.relative_to(pkg)) for p in pkg.rglob("*.py")
                     if re.search(r"\.send_message\(", p.read_text()))
    assert callers == ["sending.py"]
