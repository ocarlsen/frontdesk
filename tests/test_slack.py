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


def test_dm_unread_compares_last_read_with_others_messages(tmp_path):
    # Someone else's message after the read position is unread; the owner's own is not.
    store = Store(tmp_path / "s.db")
    convs = [{"id": "D1", "is_im": True, "user": "U0ANN"}, {"id": "D2", "is_im": True, "user": "U0BO"}]
    hist = {"D1": [{"user": "U0ANN", "ts": ts(600)}],
            "D2": [{"user": "U0BO", "ts": ts(900)}, {"user": OWNER, "ts": ts(300)}]}
    fake = ReadClient(convs, hist, {}, last_read={"D1": ts(700), "D2": ts(600)})
    sync(store, {}, TOKEN, log=lambda s: None, client=fake)
    assert "UNREAD" in store.get_item("slack:D1:dm").labels
    assert "UNREAD" not in store.get_item("slack:D2:dm").labels


# ---- unread reaches past the window -------------------------------------------------------

class ReadClient(FakeClient):
    """FakeClient with read positions (conversations.info last_read), and a log of the oldest
    timestamp each history call asked for."""

    def __init__(self, convs, histories, replies, last_read=None, info_fails=()):
        super().__init__(convs, histories, replies)
        self.last_read = last_read or {}
        self.info_fails = set(info_fails)
        self.asked: dict[str, float] = {}

    def info(self, channel):
        if channel in self.info_fails:
            raise SlackError("conversations.info", "missing_scope")
        return {"last_read": self.last_read.get(channel, "0")}

    def history(self, channel, oldest_ts):
        self.asked[channel] = float(oldest_ts)
        return super().history(channel, oldest_ts)


DAY = 86400


def _old_world():
    t_ask = ts(30 * DAY)
    convs = [{"id": "D0OLDUN", "is_im": True, "user": "U0ANN"},     # unread, 40 days old
             {"id": "D0OLDRD", "is_im": True, "user": "U0BO"},      # read, 40 days old
             {"id": "D0ANCIENT", "is_im": True, "user": "U0CY"},    # unread, past the floor
             {"id": "G0GROUP", "is_mpim": True, "name": "mpdm-ann--bo--pat-1"},   # unread group DM
             CHAN]
    hist = {
        "D0OLDUN": [{"ts": ts(40 * DAY), "user": "U0ANN", "text": "still need the W-9"}],
        "D0OLDRD": [{"ts": ts(40 * DAY), "user": "U0BO", "text": "thanks!"}],
        "D0ANCIENT": [{"ts": ts(120 * DAY), "user": "U0CY", "text": "long ago"}],
        "G0GROUP": [{"ts": ts(20 * DAY), "user": "U0BO", "text": "plan for Friday?"}],
        "C0ENG": [
            {"ts": t_ask, "user": "U0ANN", "text": f"<@{OWNER}> can you sign off?"},  # unread
            {"ts": ts(50 * DAY), "user": "U0BO", "text": f"<@{OWNER}> old, already read"},
            {"ts": ts(25 * DAY), "user": "U0BO", "text": "unread chatter, no mention"},
        ],
    }
    last_read = {"D0OLDUN": ts(41 * DAY), "D0OLDRD": ts(39 * DAY), "D0ANCIENT": "0",
                 "G0GROUP": ts(21 * DAY), "C0ENG": ts(45 * DAY)}
    return convs, hist, last_read, t_ask


def test_unread_dms_and_mentions_come_in_however_old(tmp_path):
    store = Store(tmp_path / "s.db")
    convs, hist, last_read, t_ask = _old_world()
    fake = ReadClient(convs, hist, {}, last_read=last_read)
    res = sync(store, {}, TOKEN, log=lambda s: None, client=fake)
    ids = {r["id"] for r in store.db.execute("SELECT id FROM items")}
    assert ids == {"slack:D0OLDUN:dm", "slack:G0GROUP:dm", f"slack:C0ENG:{t_ask}"}
    assert res.synced == 3
    assert "UNREAD" in store.get_item("slack:D0OLDUN:dm").labels
    assert "UNREAD" in store.get_item("slack:G0GROUP:dm").labels
    # Channel threads are never marked unread: Slack keeps one read position per channel, so
    # FrontDesk could never clear it.
    assert "UNREAD" not in store.get_item(f"slack:C0ENG:{t_ask}").labels
    # History reaches back to the read position, but no further than slack_unread_days (90).
    now = time.time()
    assert abs(fake.asked["D0OLDUN"] - (now - 41 * DAY)) < 60
    assert abs(fake.asked["D0ANCIENT"] - (now - 90 * DAY)) < 60
    # Read, but its read position is older than the window: history must reach it to know.
    assert abs(fake.asked["D0OLDRD"] - (now - 39 * DAY)) < 60


def test_reading_it_in_slack_lets_it_go_on_the_next_sync(tmp_path):
    store = Store(tmp_path / "s.db")
    convs, hist, last_read, t_ask = _old_world()
    sync(store, {}, TOKEN, log=lambda s: None, client=ReadClient(convs, hist, {}, last_read=last_read))
    caught_up = {k: ts(1) for k in last_read}
    res = sync(store, {}, TOKEN, log=lambda s: None,
               client=ReadClient(convs, hist, {}, last_read=caught_up))
    assert {r["id"] for r in store.db.execute("SELECT id FROM items")} == set()
    assert res.removed == 3


def test_no_read_position_means_the_window_only(tmp_path):
    store = Store(tmp_path / "s.db")
    convs, hist, last_read, t_ask = _old_world()
    fake = ReadClient(convs, hist, {}, last_read=last_read,
                      info_fails={"D0OLDUN", "G0GROUP", "C0ENG", "D0OLDRD", "D0ANCIENT"})
    sync(store, {}, TOKEN, log=lambda s: None, client=fake)
    assert {r["id"] for r in store.db.execute("SELECT id FROM items")} == set()
    assert all(abs(v - (time.time() - 7 * DAY)) < 60 for v in fake.asked.values())


def test_the_window_still_brings_in_recent_read_conversations(tmp_path):
    store = Store(tmp_path / "s.db")
    convs, histories, replies, t_mention, t_replied = _world()
    everything_read = {"D0ANN": ts(1), "D0OLD": ts(1), "C0ENG": ts(1)}
    sync(store, {}, TOKEN, log=lambda s: None,
         client=ReadClient(convs, histories, replies, last_read=everything_read))
    ids = {r["id"] for r in store.db.execute("SELECT id FROM items")}
    assert ids == {"slack:D0ANN:dm", f"slack:C0ENG:{t_mention}", f"slack:C0ENG:{t_replied}"}
    assert "UNREAD" not in store.get_item("slack:D0ANN:dm").labels


def test_default_cap_is_100_like_gmail(tmp_path):
    from frontdesk import config
    assert config.DEFAULTS["slack_max_items"] == config.DEFAULTS["gmail_max_threads"] == 100
    store = Store(tmp_path / "s.db")
    convs = [{"id": f"D{i:03d}", "is_im": True, "user": "U0ANN"} for i in range(120)]
    hist = {c["id"]: [{"ts": ts(60 + i), "user": "U0ANN", "text": "hi"}] for i, c in enumerate(convs)}
    logs: list[str] = []
    res = sync(store, {}, TOKEN, log=logs.append, client=ReadClient(convs, hist, {}))
    assert res.synced == 100
    assert {r["id"] for r in store.db.execute("SELECT id FROM items")} == \
        {f"slack:D{i:03d}:dm" for i in range(100)}                # the newest 100
    assert any("kept the newest 100 of 120" in line for line in logs)


def test_unread_old_dm_reaches_the_page_marked_unread(tmp_path):
    from frontdesk.web import server
    store = Store(tmp_path / "s.db")
    convs, hist, last_read, t_ask = _old_world()
    sync(store, {}, TOKEN, log=lambda s: None, client=ReadClient(convs, hist, {}, last_read=last_read))
    rows = {r["item"]["id"]: r for r in server.ranked_payload(store)}
    assert "UNREAD" in rows["slack:D0OLDUN:dm"]["item"]["labels"]


# ---- thread read state and the owner's FrontDesk marks ------------------------------------

def _thread_world(subscribed=True, thread_last_read=None, extra_reply=False, now=None):
    """A thread the owner started in #eng (no mention, no reply by them) with two replies from
    others; the parent carries the thread's own read position, as conversations.replies does."""
    now = now or time.time()

    def at(ago: float) -> str:
        return f"{now - ago:.6f}"
    root, r1, r2 = at(5 * 3600), at(3 * 3600), at(2 * 3600)
    parent = {"ts": root, "thread_ts": root, "user": OWNER, "text": "shipping today?",
              "reply_count": 2, "reply_users": ["U0ANN", "U0BO"], "latest_reply": r2,
              "subscribed": subscribed}
    if thread_last_read is not None:
        parent["last_read"] = thread_last_read
    replies = [parent, {"ts": r1, "thread_ts": root, "user": "U0ANN", "text": "yes"},
               {"ts": r2, "thread_ts": root, "user": "U0BO", "text": "after lunch"}]
    if extra_reply:
        r3 = at(60)
        replies.append({"ts": r3, "thread_ts": root, "user": "U0ANN", "text": "done"})
        parent["latest_reply"] = r3
    hist = {"C0ENG": [{k: v for k, v in parent.items() if k not in ("subscribed", "last_read")}]}
    return [CHAN], hist, {("C0ENG", root): replies}, root, r1


def test_a_thread_the_owner_started_comes_in(tmp_path):
    store = Store(tmp_path / "s.db")
    convs, hist, replies, root, _ = _thread_world()
    sync(store, {}, TOKEN, log=lambda s: None, client=ReadClient(convs, hist, replies))
    assert store.get_item(f"slack:C0ENG:{root}") is not None


@pytest.mark.parametrize("subscribed,read_to,unread", [
    (True, "r1", True),        # followed, a reply after the read position: unread
    (True, "now", False),      # followed, read to the end
    (False, "r1", False),      # not followed: Slack's position is not the owner's to trust
    (True, None, False),       # followed but no position given: never guess
])
def test_thread_unread_comes_from_its_own_read_position(tmp_path, subscribed, read_to, unread):
    store = Store(tmp_path / "s.db")
    now = time.time()
    _, _, _, _, r1 = _thread_world(now=now)
    pos = {"r1": r1, "now": ts(1), None: None}[read_to]
    convs, hist, replies, root, _ = _thread_world(subscribed=subscribed, thread_last_read=pos,
                                                  now=now)
    sync(store, {}, TOKEN, log=lambda s: None, client=ReadClient(convs, hist, replies))
    assert ("UNREAD" in store.get_item(f"slack:C0ENG:{root}").labels) is unread


def test_channel_without_a_read_position_gets_the_window_only(tmp_path):
    store = Store(tmp_path / "s.db")
    convs, hist, last_read, t_ask = _old_world()
    channel_only = {k: v for k, v in last_read.items() if k != "C0ENG"}

    class NoChannelPos(ReadClient):
        def info(self, channel):
            return {} if channel == "C0ENG" else super().info(channel)
    fake = NoChannelPos(convs, hist, {}, last_read=channel_only)
    sync(store, {}, TOKEN, log=lambda s: None, client=fake)
    assert store.get_item(f"slack:C0ENG:{t_ask}") is None          # the old mention stays out
    assert abs(fake.asked["C0ENG"] - (time.time() - 7 * DAY)) < 60


def test_marked_unread_here_survives_syncs_until_read_in_slack(tmp_path):
    from frontdesk import actions
    from frontdesk.web import server
    store = Store(tmp_path / "s.db")
    now = time.time()
    convs, hist, replies, root, _ = _thread_world(thread_last_read=ts(1), now=now)   # read in Slack
    item_id = f"slack:C0ENG:{root}"
    sync(store, {}, TOKEN, log=lambda s: None, client=ReadClient(convs, hist, replies))
    actions.mark_unread(store, item_id, None)
    sync(store, {}, TOKEN, log=lambda s: None, client=ReadClient(convs, hist, replies))
    row = next(r for r in server.ranked_payload(store) if r["item"]["id"] == item_id)
    assert "UNREAD" in row["item"]["labels"]                       # a sync that sees read: kept
    later = f"{time.time() + 5:.6f}"                                # read further in Slack
    convs, hist, replies, root, _ = _thread_world(thread_last_read=later, now=now)
    sync(store, {}, TOKEN, log=lambda s: None, client=ReadClient(convs, hist, replies))
    row = next(r for r in server.ranked_payload(store) if r["item"]["id"] == item_id)
    assert "UNREAD" not in row["item"]["labels"]


def test_read_here_survives_syncs_until_a_new_reply(tmp_path):
    from frontdesk import actions
    from frontdesk.web import server
    store = Store(tmp_path / "s.db")
    now = time.time()
    _, _, _, _, r1 = _thread_world(now=now)
    convs, hist, replies, root, _ = _thread_world(thread_last_read=r1, now=now)   # unread in Slack
    item_id = f"slack:C0ENG:{root}"
    sync(store, {}, TOKEN, log=lambda s: None, client=ReadClient(convs, hist, replies))
    assert "UNREAD" in store.get_item(item_id).labels
    assert actions.mark_read(store, item_id, None)["here_only"] is True
    sync(store, {}, TOKEN, log=lambda s: None, client=ReadClient(convs, hist, replies))
    row = next(r for r in server.ranked_payload(store) if r["item"]["id"] == item_id)
    assert "UNREAD" not in row["item"]["labels"]                   # Slack still unread: kept read
    convs, hist, replies, root, _ = _thread_world(thread_last_read=r1, extra_reply=True, now=now)
    sync(store, {}, TOKEN, log=lambda s: None, client=ReadClient(convs, hist, replies))
    assert "UNREAD" in store.get_item(item_id).labels              # a new reply: unread again


# ---- Keep for Slack search matches --------------------------------------------------------

class KeepClient(ReadClient):
    """conversations.info answers with the conversation itself, as Slack does."""

    def info(self, channel):
        conv = next((c for c in self.convs if c["id"] == channel), {"id": channel})
        return {**conv, "last_read": self.last_read.get(channel, "0")}


def _keep_world(now):
    old = f"{now - 60 * DAY:.6f}"                 # quiet for 60 days: outside the window
    r1 = f"{now - 59 * DAY:.6f}"
    thread = [{"ts": old, "thread_ts": old, "user": "U0ANN", "text": "budget for Q3?",
               "reply_count": 1, "reply_users": ["U0BO"], "latest_reply": r1},
              {"ts": r1, "thread_ts": old, "user": "U0BO", "text": "approved"}]
    convs = [CHAN, {"id": "D0QUIET", "is_im": True, "user": "U0ANN"}]
    hist = {"C0ENG": [thread[0]], "D0QUIET": [{"ts": old, "user": "U0ANN", "text": "see you"}]}
    return convs, hist, {("C0ENG", old): thread}, old


def test_keep_slack_stores_ranks_and_sync_keeps_it_current(tmp_path, monkeypatch):
    from frontdesk.web import server
    now = time.time()
    convs, hist, replies, old = _keep_world(now)
    db = tmp_path / "s.db"
    Store(db).db.close()
    fake = KeepClient(convs, hist, replies, last_read={"C0ENG": old, "D0QUIET": old})

    class Provider:
        calls = 0
    monkeypatch.setattr("frontdesk.triage.triage_item",
                        lambda p, item, profile="": (_ for _ in ()).throw(
                            __import__("frontdesk.providers", fromlist=["ProviderError"]).ProviderError("offline")))
    code, out = server.keep_slack(db, {}, f"slack:C0ENG:{old}", slack_factory=lambda: fake,
                                  provider_factory=lambda: Provider())
    assert code == 200 and out["kind"] == "keep"
    code, _ = server.keep_slack(db, {}, "slack:D0QUIET:dm", slack_factory=lambda: fake,
                                provider_factory=lambda: Provider())
    assert code == 200
    store = Store(db)
    thread = store.get_item(f"slack:C0ENG:{old}")
    assert [m.body for m in thread.messages] == ["budget for Q3?", "approved"]
    assert store.is_kept(thread.id) and store.is_kept("slack:D0QUIET:dm")
    # Both are 60 days quiet, outside the window: sync keeps them, and fetches a new reply.
    replies[("C0ENG", old)].append({"ts": f"{now - 60:.6f}", "thread_ts": old, "user": "U0ANN",
                                    "text": "thanks"})
    sync(store, {}, TOKEN, log=lambda s: None, client=fake)
    assert [m.body for m in store.get_item(f"slack:C0ENG:{old}").messages][-1] == "thanks"
    assert store.get_item("slack:D0QUIET:dm") is not None
    # Marked done: the next sync lets it go.
    from frontdesk import actions
    actions.set_done(store, f"slack:C0ENG:{old}", True)
    sync(store, {}, TOKEN, log=lambda s: None, client=fake)
    assert store.get_item(f"slack:C0ENG:{old}") is None


@pytest.mark.parametrize("item_id", ["slack:C0ENG:abc", "slack:../x:dm", "gmail:abc", ""])
def test_keep_slack_refuses_other_ids(tmp_path, item_id):
    from frontdesk.web import server
    code, _ = server.keep_slack(tmp_path / "s.db", {}, item_id, slack_factory=lambda: None)
    assert code == 400


def test_keep_slack_is_refused_in_demo_mode(tmp_path):
    from frontdesk.web import server
    code, _ = server.keep_slack(tmp_path / "s.db", {"demo": True}, "slack:C0ENG:1740000000.000100",
                                slack_factory=lambda: None)
    assert code == 409
