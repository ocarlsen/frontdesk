"""Slack in search: rows from search.messages keyed like the items sync makes, run beside Gmail,
each source failing on its own, and nothing stored."""
from __future__ import annotations

from http import HTTPStatus

import requests

from frontdesk.slack.client import SlackError
from frontdesk.slack.search import match_row
from frontdesk.web.server import run_search

LINK = "https://acme.slack.com/archives/C111/p1793000100000200"


def m(ch: dict, ts="1793000100.000200", link=LINK, text="Budget line by Friday?", user="dana"):
    return {"channel": ch, "ts": ts, "permalink": link, "text": text, "username": user}


def test_ids_match_what_sync_would_call_the_conversation():
    assert match_row(m({"id": "D1", "is_im": True}))["id"] == "slack:D1:dm"
    assert match_row(m({"id": "G1", "is_mpim": True}))["id"] == "slack:G1:dm"
    root = match_row(m({"id": "C111", "name": "analytics"}))
    assert root["id"] == "slack:C111:1793000100.000200" and root["where"] == "#analytics"
    reply = match_row(m({"id": "C111", "name": "analytics"}, ts="1793000200.000300",
                        link=LINK + "?thread_ts=1793000100.000200&cid=C111"))
    assert reply["id"] == "slack:C111:1793000100.000200"      # a reply belongs to its root


def test_text_is_capped_and_only_slack_links_are_kept():
    r = match_row(m({"id": "C1", "name": "x"}, text="y" * 900, link="javascript:alert(1)"))
    assert len(r["text"]) <= 401 and r["url"] == ""
    assert match_row({"channel": {}, "ts": ""}) is None


class Gmail:
    def __init__(self, exc=None):
        self.exc = exc

    def profile_email(self):
        return "owner@example.com"

    def list_thread_ids(self, q, n):
        if self.exc:
            raise self.exc
        return []

    def get_thread(self, tid, fmt="full"):
        raise AssertionError("no threads")


class Slack:
    def __init__(self, exc=None):
        self.exc, self.queries = exc, []

    def search_messages(self, q, count=20):
        self.queries.append((q, count))
        if self.exc:
            raise self.exc
        return [m({"id": "C111", "name": "analytics"})]


def test_both_sources_together():
    s = Slack()
    code, out = run_search({}, "budget", client_factory=Gmail, slack_factory=lambda: s)
    assert code == HTTPStatus.OK and out["results"] == [] and s.queries == [("budget", 20)]
    assert [r["id"] for r in out["slack"]] == ["slack:C111:1793000100.000200"]
    assert out["gmail_error"] == "" and out["slack_error"] == ""


def test_one_source_failing_does_not_hide_the_other():
    code, out = run_search({}, "x", client_factory=lambda: Gmail(requests.ConnectionError("x")),
                           slack_factory=Slack)
    assert code == HTTPStatus.OK and out["gmail_error"] == "Gmail did not answer"
    assert len(out["slack"]) == 1
    code, out = run_search({}, "x", client_factory=Gmail,
                           slack_factory=lambda: Slack(SlackError("search.messages", "missing_scope")))
    assert code == HTTPStatus.OK and out["slack"] == [] and "search:read" in out["slack_error"]
    code, out = run_search({}, "x", client_factory=Gmail,
                           slack_factory=lambda: Slack(requests.ConnectionError("x")))
    assert out["slack_error"] == "Slack did not answer"


def test_without_a_slack_connection_there_is_no_slack_section():
    code, out = run_search({}, "x", client_factory=Gmail)
    assert code == HTTPStatus.OK and out["slack"] is None


def test_snippets_read_as_slack_shows_them():
    from frontdesk.slack.normalize import emojize, plain_mrkdwn
    r = match_row(m({"id": "C1", "name": "alerts"},
                    text=":mag: *Root cause:* the `frontdesk` key &amp; <#C2|finance>, _maybe_"))
    assert r["text"] == "\U0001F50D Root cause: the frontdesk key & #finance, maybe"
    assert emojize("at 10:30:00 :not_a_known_one:") == "at 10:30:00 :not_a_known_one:"
    assert plain_mrkdwn("snake_case_name and 2*3*4") == "snake_case_name and 2*3*4"
