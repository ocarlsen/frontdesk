"""Slack ingest on synthetic payloads only: invented people, workspace example-team.slack.com,
no network. The client test inspects the exact request requests would send."""
from __future__ import annotations

import json
import time

import pytest
import requests

from frontdesk.items import Item, Message
from frontdesk.slack import client as client_mod
from frontdesk.slack.client import SlackClient, SlackError
from frontdesk.slack.normalize import dm_to_item, readable, thread_to_item, to_message
from frontdesk.slack.sync import sync
from frontdesk.store import Store

HOST = "example-team.slack.com"
OWNER = "U0OWNER"
NAMES = {OWNER: "Pat Owner", "U0ANN": "Ann Lee", "U0BO": "Bo Diaz", "U0CY": "Cy Park"}
TOKEN = "xoxp-test-secret-123"
TEAM = "T0"


def key(uid: str) -> str:
    return f"slack:t0:{uid.lower()}"


def name_of(uid: str) -> str:
    return NAMES.get(uid, uid)


def ts(seconds_ago: float) -> str:
    return f"{time.time() - seconds_ago:.6f}"


# ---- markup and messages ------------------------------------------------------------------

@pytest.mark.parametrize("raw,want", [
    ("hi <@U0ANN>", "hi @Ann Lee"),
    ("see <#C0GEN|general>", "see #general"),
    ("<https://x.example/a|the doc>", "the doc (https://x.example/a)"),
    ("<https://x.example/a>", "https://x.example/a"),
    ("<https://x.example/a|https://x.example/a>", "https://x.example/a"),
    ("<mailto:ann@example.com|ann@example.com>", "ann@example.com"),
    ("<!here> ship it", "@here ship it"),
    ("<!subteam^S01|@eng> look", "@eng look"),
    ("a &amp; b &lt;c&gt;", "a & b <c>"),
    ("literal &lt;@U0ANN&gt;", "literal <@U0ANN>"),   # typed text, not a mention
])
def test_markup(raw, want):
    assert readable(raw, name_of) == want


def test_bot_detection_and_is_mine():
    bot = {"ts": "1700000000.000100", "subtype": "bot_message", "bot_id": "B1",
           "username": "Deploybot", "text": "deployed"}
    app = {"ts": "1700000000.000200", "bot_id": "B2", "user": "U0BO",
           "bot_profile": {"name": "Calendar"}, "text": "meeting soon"}
    mine = {"ts": "1700000000.000300", "user": OWNER, "text": "ok"}
    assert to_message(bot, OWNER, name_of, TEAM).sender == "Deploybot (bot)"
    assert to_message(app, OWNER, name_of, TEAM).sender == "Calendar (bot)"
    m = to_message(mine, OWNER, name_of, TEAM)
    assert (m.sender, m.is_mine, m.html) == ("Pat Owner", True, "")
    assert m.sent_at == "2023-11-14T22:13:20Z"
    assert not to_message(bot, OWNER, name_of, TEAM).is_mine


def test_system_subtypes_skipped():
    for sub in ("channel_join", "channel_leave", "channel_topic", "pinned_item"):
        assert to_message({"ts": "1.0", "user": "U0ANN", "subtype": sub, "text": "x"},
                          OWNER, name_of, TEAM) is None


def test_file_only_message_has_a_body():
    m = to_message({"ts": "1.0", "user": "U0ANN", "subtype": "file_share", "text": "",
                    "files": [{"name": "plan.pdf"}]}, OWNER, name_of, TEAM)
    assert m.body == "[file: plan.pdf]"


# ---- DMs ----------------------------------------------------------------------------------

def test_dm_grouped_oldest_first():
    conv = {"id": "D0ANN", "is_im": True, "user": "U0ANN"}
    raw = [  # history order: newest first
        {"ts": "1700000300.000000", "user": OWNER, "text": "sure"},
        {"ts": "1700000200.000000", "user": "U0ANN", "subtype": "channel_join"},
        {"ts": "1700000100.000000", "user": "U0ANN", "text": "lunch?"},
    ]
    item = dm_to_item(conv, raw, OWNER, HOST, name_of, TEAM)
    assert item.id == "slack:D0ANN:dm"
    assert (item.source, item.account) == ("slack", HOST)
    assert item.subject == "Slack DM with Ann Lee"
    assert [m.body for m in item.messages] == ["lunch?", "sure"]
    assert [m.is_mine for m in item.messages] == [False, True]
    assert item.participants == [key("U0ANN"), key(OWNER)]
    assert [m.sender for m in item.messages] == ["Ann Lee", "Pat Owner"]   # names stay for display
    assert [m.sender_key for m in item.messages] == [key("U0ANN"), key(OWNER)]
    assert item.names == {key("U0ANN"): "Ann Lee", key(OWNER): "Pat Owner"}
    assert item.owner_key == key(OWNER)
    assert item.updated_at == "2023-11-14T22:18:20Z"
    assert item.labels == ["slack", "dm"]
    assert item.url == f"https://{HOST}/archives/D0ANN/p1700000300000000"


def test_group_dm_subject():
    conv = {"id": "G0GRP", "is_mpim": True, "name": "mpdm-ann--bo--pat-1"}
    raw = [{"ts": "2.0", "user": "U0BO", "text": "b"}, {"ts": "1.0", "user": "U0ANN", "text": "a"}]
    item = dm_to_item(conv, raw, OWNER, HOST, name_of, TEAM)
    assert item.subject == "Slack group DM: Ann Lee, Bo Diaz"
    assert item.labels == ["slack", "group_dm"]
    only_me = dm_to_item(conv, [{"ts": "1.0", "user": OWNER, "text": "hi"}], OWNER, HOST, name_of, TEAM)
    assert only_me.subject == "Slack group DM: ann, bo, pat"


def test_dm_with_only_system_events_is_none():
    conv = {"id": "D0ANN", "is_im": True, "user": "U0ANN"}
    assert dm_to_item(conv, [{"ts": "1.0", "subtype": "channel_join"}], OWNER, HOST,
                      name_of, TEAM) is None


# ---- channel threads ----------------------------------------------------------------------

CHAN = {"id": "C0ENG", "name": "eng", "is_member": True}


def test_thread_item_and_urls():
    root = {"ts": "1700000000.000100", "thread_ts": "1700000000.000100", "user": "U0ANN",
            "text": f"<@{OWNER}> can you review?\nsecond line", "reply_count": 1}
    reply = {"ts": "1700000500.000200", "thread_ts": "1700000000.000100", "user": OWNER,
             "text": "on it"}
    item = thread_to_item(CHAN, [root, reply, root], OWNER, HOST, name_of, TEAM)  # root repeated
    assert item.id == "slack:C0ENG:1700000000.000100"
    assert item.subject == "#eng: @Pat Owner can you review?"
    assert len(item.messages) == 2
    assert item.labels == ["slack", "channel"]
    assert item.url == (f"https://{HOST}/archives/C0ENG/p1700000000000100"
                        "?thread_ts=1700000000.000100&cid=C0ENG")
    single = thread_to_item(CHAN, [{"ts": "1700000000.000100", "user": "U0ANN",
                                    "text": "x" * 200}], OWNER, HOST, name_of, TEAM)
    assert single.url == f"https://{HOST}/archives/C0ENG/p1700000000000100"
    assert single.subject == "#eng: " + "x" * 80


# ---- sync with a fake client --------------------------------------------------------------

class FakeClient:
    def __init__(self, convs, histories, replies, fail=()):
        self.convs, self.histories, self.thread_replies = convs, histories, replies
        self.fail = set(fail)
        self.replies_calls: list[tuple[str, str]] = []

    def auth_test(self):
        return {"user_id": OWNER, "team_id": "T0", "url": f"https://{HOST}/",
                "team": "Example", "user": "pat"}

    def list_conversations(self):
        return self.convs

    def history(self, channel, oldest_ts):
        if channel in self.fail:
            raise SlackError("conversations.history", "missing_scope")
        return [m for m in self.histories.get(channel, []) if float(m["ts"]) >= float(oldest_ts)]

    def replies(self, channel, thread_ts):
        self.replies_calls.append((channel, thread_ts))
        return self.thread_replies[(channel, thread_ts)]

    def user(self, uid):
        if uid not in NAMES:
            raise SlackError("users.info", "user_not_found")
        return {"id": uid, "profile": {"display_name": NAMES[uid]}}


def _world():
    t_mention, t_replied, t_plain, t_dm = ts(3600), ts(7200), ts(1800), ts(600)
    t_bc = ts(900)
    convs = [{"id": "D0ANN", "is_im": True, "user": "U0ANN"},
             {"id": "D0OLD", "is_im": True, "user": "U0CY"},
             CHAN]
    histories = {
        "D0ANN": [{"ts": t_dm, "user": "U0ANN", "text": "ping"}],
        "D0OLD": [{"ts": ts(30 * 86400), "user": "U0CY", "text": "ancient"}],
        "C0ENG": [
            {"ts": t_plain, "user": "U0BO", "text": "unrelated chatter"},
            {"ts": t_bc, "thread_ts": t_plain, "user": "U0BO", "subtype": "thread_broadcast",
             "text": f"echo <@{OWNER}>"},
            {"ts": t_mention, "user": "U0ANN", "text": f"<@{OWNER}> thoughts?"},
            {"ts": t_replied, "thread_ts": t_replied, "user": "U0BO", "text": "design q",
             "reply_count": 2, "reply_users": ["U0ANN", OWNER], "latest_reply": ts(60)},
            {"ts": ts(100), "user": "U0ANN", "subtype": "channel_join", "text": f"<@{OWNER}>"},
        ],
    }
    replies = {("C0ENG", t_replied): [
        {"ts": t_replied, "thread_ts": t_replied, "user": "U0BO", "text": "design q"},
        {"ts": ts(300), "thread_ts": t_replied, "user": OWNER, "text": "use a queue"},
        {"ts": ts(60), "thread_ts": t_replied, "user": "U0ANN", "text": "agreed"},
    ]}
    return convs, histories, replies, t_mention, t_replied


def test_sync_selects_and_prunes(tmp_path):
    store = Store(tmp_path / "s.db")
    stale = Item(id="slack:C0ENG:1.000000", source="slack", account=HOST, subject="old",
                 participants=[], messages=[Message("x", "2020-01-01T00:00:00Z", "b")],
                 updated_at="2020-01-01T00:00:00Z")
    other = Item(id="slack:C9:1.0", source="slack", account="other.slack.com", subject="o",
                 participants=[], messages=[Message("x", "2020-01-01T00:00:00Z", "b")],
                 updated_at="2020-01-01T00:00:00Z")
    store.upsert_item(stale)
    store.upsert_item(other)
    convs, histories, replies, t_mention, t_replied = _world()
    fake = FakeClient(convs, histories, replies)
    logs: list[str] = []
    res = sync(store, {"slack_days": 7}, TOKEN, log=logs.append, client=fake)

    ids = {r["id"] for r in store.db.execute("SELECT id FROM items")}
    assert ids == {"slack:D0ANN:dm", f"slack:C0ENG:{t_mention}", f"slack:C0ENG:{t_replied}",
                   "slack:C9:1.0"}          # other workspace untouched
    assert (res.synced, res.removed) == (3, 1)
    assert fake.replies_calls == [("C0ENG", t_replied)]   # only the thread with replies
    thread = store.get_item(f"slack:C0ENG:{t_replied}")
    assert [m.body for m in thread.messages] == ["design q", "use a queue", "agreed"]
    assert thread.messages[1].is_mine
    assert store.get_item(f"slack:C0ENG:{t_mention}").subject == "#eng: @Pat Owner thoughts?"
    assert not any(TOKEN in line for line in logs)


def test_sync_cap_keeps_newest(tmp_path):
    store = Store(tmp_path / "s.db")
    convs, histories, replies, t_mention, t_replied = _world()
    res = sync(store, {"slack_max_items": 2}, TOKEN, log=lambda s: None,
               client=FakeClient(convs, histories, replies))
    ids = {r["id"] for r in store.db.execute("SELECT id FROM items")}
    # newest activity: the DM (10 min ago), then the replied thread (latest reply 1 min ago)
    assert ids == {"slack:D0ANN:dm", f"slack:C0ENG:{t_replied}"}
    assert res.synced == 2


def test_sync_failed_conversation_keeps_its_items(tmp_path):
    store = Store(tmp_path / "s.db")
    convs, histories, replies, t_mention, t_replied = _world()
    sync(store, {}, TOKEN, log=lambda s: None, client=FakeClient(convs, histories, replies))
    logs: list[str] = []
    res = sync(store, {}, TOKEN, log=logs.append,
               client=FakeClient(convs, histories, replies, fail={"C0ENG"}))
    assert store.get_item(f"slack:C0ENG:{t_mention}") is not None
    assert res.removed == 0
    assert any("skipped conversation C0ENG: SlackError" in line for line in logs)


# ---- the HTTP client ----------------------------------------------------------------------

def _response(status: int, payload: dict, headers: dict | None = None) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r._content = json.dumps(payload).encode()
    r.headers.update(headers or {})
    return r


def test_token_only_in_header_and_pagination(monkeypatch):
    c = SlackClient(TOKEN)
    sent: list[requests.PreparedRequest] = []
    pages = [_response(200, {"ok": True, "messages": [{"ts": "2.0"}],
                             "response_metadata": {"next_cursor": "abc"}}),
             _response(200, {"ok": True, "messages": [{"ts": "1.0"}],
                             "response_metadata": {"next_cursor": ""}})]

    def fake_send(req, **kw):
        sent.append(req)
        return pages.pop(0)
    monkeypatch.setattr(c.session, "send", fake_send)
    msgs = c.history("C0ENG", "1.0")
    assert [m["ts"] for m in msgs] == ["2.0", "1.0"]
    assert len(sent) == 2
    for req in sent:
        assert TOKEN not in req.url
        assert req.headers["Authorization"] == f"Bearer {TOKEN}"
        assert req.method == "GET"
    assert "cursor=abc" in sent[1].url and "channel=C0ENG" in sent[0].url
    assert TOKEN not in repr(c)


def test_retry_on_429_then_error_code_only(monkeypatch):
    c = SlackClient(TOKEN)
    sleeps: list[float] = []
    monkeypatch.setattr(client_mod.time, "sleep", sleeps.append)
    seq = [_response(429, {"ok": False}, {"Retry-After": "3"}),
           _response(503, {}),
           _response(200, {"ok": False, "error": "channel_not_found", "detail": "secret text"})]
    monkeypatch.setattr(c.session, "send", lambda req, **kw: seq.pop(0))
    with pytest.raises(SlackError) as e:
        c.replies("C0X", "1.0")
    assert sleeps == [3.0, 2.0]
    assert str(e.value) == "Slack API conversations.replies: channel_not_found"


def test_list_conversations_filters_and_user_cache(monkeypatch):
    c = SlackClient(TOKEN)
    calls: list[str] = []

    def fake_send(req, **kw):
        calls.append(req.url)
        if "conversations.list" in req.url:
            return _response(200, {"ok": True, "channels": [
                {"id": "C1", "is_member": True}, {"id": "C2", "is_member": False},
                {"id": "D1", "is_im": True}]})
        return _response(200, {"ok": True, "user": {"id": "U0ANN", "name": "ann"}})
    monkeypatch.setattr(c.session, "send", fake_send)
    assert [x["id"] for x in c.list_conversations()] == ["C1", "D1"]
    assert "types=im%2Cmpim%2Cprivate_channel%2Cpublic_channel" in calls[0]
    c.user("U0ANN")
    c.user("U0ANN")
    assert sum("users.info" in u for u in calls) == 1


def test_dm_unread_compares_last_read_with_others_messages():
    from frontdesk.slack.sync import _dm_unread

    class C:
        def __init__(self, last_read):
            self.last_read = last_read

        def info(self, ch):
            return {"last_read": self.last_read}
    msgs = [{"user": "U0ANN", "ts": "1730000000.000200"},
            {"user": "U0OWNER", "ts": "1730000000.000300"}]
    assert _dm_unread(C("1730000000.000100"), "D1", msgs, "U0OWNER") is True
    assert _dm_unread(C("1730000000.000200"), "D1", msgs, "U0OWNER") is False   # only own after

    class Broken:
        def info(self, ch):
            raise RuntimeError("missing_scope")
    assert _dm_unread(Broken(), "D1", msgs, "U0OWNER") is False
