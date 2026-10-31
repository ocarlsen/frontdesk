"""Search all of Gmail: rows from metadata fetches, nothing stored, loud and leak-free failures."""
from __future__ import annotations

from http import HTTPStatus

import requests

from frontdesk.gmail.auth import AuthError
from frontdesk.gmail.client import GmailError
from frontdesk.gmail.search import thread_row
from frontdesk.web.server import search_gmail

ME = "owner@example.com"


def _m(mid, ms, frm, labels, subject="Lunch"):
    return {"id": mid, "internalDate": str(ms), "labelIds": labels,
            "payload": {"headers": [{"name": "From", "value": frm},
                                    {"name": "Subject", "value": subject}]}}


class G:
    def __init__(self, threads=None, exc=None):
        self.threads, self.exc, self.calls = threads or {}, exc, []

    def profile_email(self):
        return ME

    def list_thread_ids(self, query, max_threads):
        self.calls.append(("list", query, max_threads))
        if self.exc:
            raise self.exc
        return list(self.threads)

    def get_thread(self, tid, fmt="full"):
        self.calls.append(("get", tid, fmt))
        return self.threads[tid]


def test_row_uses_newest_sender_and_first_subject_and_skips_drafts():
    t = {"id": "t1", "messages": [
        _m("a", 1000, "Ann <ann@example.com>", ["INBOX", "UNREAD"], "Lunch Friday"),
        _m("b", 3000, f"Me <{ME}>", ["SENT"], "Re: Lunch Friday"),
        _m("c", 5000, f"Me <{ME}>", ["DRAFT"]),
    ]}
    row = thread_row(t, ME)
    assert row["id"] == "gmail:t1" and row["subject"] == "Lunch Friday"
    assert row["from_me"] and row["messages"] == 2 and row["in_inbox"] and row["unread"]
    assert row["url"].endswith("#all/t1") and "authuser=owner@example.com" in row["url"]
    assert thread_row({"id": "t2", "messages": [_m("d", 1, ME, ["DRAFT"])]}, ME) is None


def test_archived_thread_is_found_and_marked():
    row = thread_row({"id": "t3", "messages": [_m("a", 1000, "Bo <bo@example.com>", ["CATEGORY_UPDATES"])]}, ME)
    assert not row["in_inbox"] and not row["from_me"]


def test_route_passes_the_query_through_fetches_metadata_and_caps_at_20():
    g = G({"t1": {"id": "t1", "messages": [_m("a", 1000, "Ann <ann@example.com>", ["INBOX"])]}})
    code, out = search_gmail({}, "  from:ann has:attachment ", client_factory=lambda: g)
    assert code == HTTPStatus.OK and [r["id"] for r in out["results"]] == ["gmail:t1"]
    assert g.calls[0] == ("list", "from:ann has:attachment", 20)
    assert g.calls[1] == ("get", "t1", "metadata")


def test_empty_or_long_query_and_demo_never_reach_gmail():
    g = G()
    assert search_gmail({}, "   ", client_factory=lambda: g)[0] == HTTPStatus.BAD_REQUEST
    assert search_gmail({}, "x" * 501, client_factory=lambda: g)[0] == HTTPStatus.BAD_REQUEST
    assert search_gmail({"demo": True}, "lunch", client_factory=lambda: g) == \
        (HTTPStatus.OK, {"results": [], "demo": True})
    assert g.calls == []


def test_failures_are_loud_and_never_echo_gmail_text():
    code, out = search_gmail({}, "x", client_factory=lambda: G(exc=GmailError(500, "threads", "<body>")))
    assert code == HTTPStatus.BAD_GATEWAY and out == {"error": "Gmail did not answer"}
    code, _ = search_gmail({}, "x", client_factory=lambda: G(exc=requests.ConnectionError("x")))
    assert code == HTTPStatus.BAD_GATEWAY
    code, out = search_gmail({}, "x", client_factory=lambda: G(exc=AuthError("Gmail sign-in needed.")))
    assert code == HTTPStatus.BAD_GATEWAY and "sign-in" in out["error"]
