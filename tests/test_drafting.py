"""Drafts: links survive byte for byte, replies thread correctly, recipients come from the thread."""
from __future__ import annotations

import base64

from frontdesk import drafting

ME = "alex@example.com"
LONG = "https://calendar.example.com/r/abc?x=1&y=two%20words&z=%E2%9C%93#frag"
SHORT = "https://example.org/a"


def roundtrip(msg) -> dict:
    return drafting.audit_raw(msg.as_bytes())


def test_links_are_byte_identical_in_both_parts():
    body = f"Two links: {LONG} and ({SHORT}).\n" + "x" * 200 + "\n"
    rep = roundtrip(drafting.build_mime(ME, ["b@example.com"], "Hi", body))
    assert rep["pass"] and rep["redirects"] == []
    assert LONG in rep["links"] and SHORT in rep["links"]
    assert not any(u.endswith((")", ".")) for u in rep["links"])
    assert not any("&amp;" in u for u in rep["links"])


def test_html_body_kept_verbatim():
    html = f'<p>See <a href="{LONG}">the invite</a></p>'
    rep = roundtrip(drafting.build_mime(ME, ["b@example.com"], "Hi", html, is_html=True))
    assert LONG in rep["links"] and rep["pass"]


def test_audit_catches_google_redirects_and_fails_closed_on_empty():
    bad = drafting.build_mime(ME, ["b@example.com"], "Hi",
                              "https://www.google.com/url?q=https://example.org/a&sa=D")
    rep = roundtrip(bad)
    assert not rep["pass"] and rep["redirects"]
    assert drafting.audit_raw(b"")["pass"] is False


def _m(mid, ms, frm, labels, extra=()):
    hs = [{"name": "From", "value": frm}, {"name": "To", "value": f"{ME}, carol@example.com"},
          {"name": "Subject", "value": "Plans"}, {"name": "Message-ID", "value": f"<{mid}@x>"}]
    return {"id": mid, "internalDate": str(ms), "labelIds": labels,
            "payload": {"headers": hs + [dict(h) for h in extra]}}


def thread():
    return {"id": "T1", "messages": [
        _m("m1", 1000, "Bob <bob@example.com>", ["INBOX"],
           [{"name": "References", "value": "<m0@x>"}]),
        _m("m2", 2000, f"Alex <{ME}>", ["SENT"]),
        _m("m3", 3000, f"Alex <{ME}>", ["INBOX"]),   # claims the owner sent it: never a reply target
    ]}


def test_reply_context_uses_latest_inbound_and_skips_owner():
    ctx = drafting.reply_context(thread(), ME)
    # m3 claims to be from the owner, so it is not a message to reply TO; m1 is
    assert ctx["to"] == ["bob@example.com"]
    assert ctx["in_reply_to"] == "<m1@x>" and ctx["references"] == "<m0@x>"
    assert ctx["subject"] == "Re: Plans" and ctx["thread_id"] == "T1"


def test_reply_to_header_wins_and_reply_all_adds_cc_without_owner():
    t = thread()
    t["messages"][0]["payload"]["headers"].append(
        {"name": "Reply-To", "value": "desk@example.com"})
    ctx = drafting.reply_context(t, ME, reply_all=True)
    assert ctx["to"] == ["desk@example.com"]
    assert ctx["cc"] == ["carol@example.com"]


class FakeGmail:
    def __init__(self):
        self.posted = None

    def profile_email(self):
        return ME

    def get_thread(self, tid):
        return thread()

    def create_draft(self, body):
        self.posted = body
        return {"id": "d1", "message": {"id": "msg1", "threadId": body["message"].get(
            "threadId", "new")}}


def test_draft_reply_posts_threaded_raw_mime():
    g = FakeGmail()
    d = drafting.draft_reply(g, "T1", f"Sounds good: {SHORT}")
    raw = base64.urlsafe_b64decode(g.posted["message"]["raw"])
    assert g.posted["message"]["threadId"] == "T1"
    assert b"In-Reply-To: <m1@x>" in raw and b"References: <m0@x> <m1@x>" in raw
    assert b"To: bob@example.com" in raw
    assert d.draft_id == "d1" and "authuser=alex@example.com" in d.url
    assert drafting.audit_raw(raw)["pass"]


def test_new_draft_needs_a_recipient():
    import pytest
    with pytest.raises(drafting.DraftError):
        drafting.build_mime(ME, [], "s", "b")
