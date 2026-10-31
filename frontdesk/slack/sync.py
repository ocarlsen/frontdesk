"""Pull recent Slack DMs and the channel threads that involve the owner into the store.

What counts as involving the owner in a channel: a thread or top-level message in the window
that @-mentions them, or a thread in the window they replied in (thread roots carry
reply_users, so this needs no per-thread fetch to decide). Everything else in a channel is
background and stays out. Upsert by id makes a re-run idempotent, as for Gmail.

Unread reaches past the window: a DM or group DM with a message from someone else after the
owner's read position comes in however old it is, and so does a channel message that
@-mentions them after their read position in that channel, back to slack_unread_days. A thread
the owner started also comes in once it has replies.

Unread labels: a DM is unread when someone else posted after its read position; a channel
thread when the owner follows it and a reply came after the thread's own read position
(conversations.replies carries both). Slack documents last_read for DMs only; a channel's or
thread's is used when present and never guessed when not. Marks the owner made in FrontDesk win
until Slack moves on (see the local_unread and local_read tables)."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

from ..gmail.sync import SyncResult
from ..store import Store
from .client import SlackClient, SlackError
from .normalize import display_name, dm_to_item, is_system, mentions, thread_to_item


@dataclass
class _Candidate:
    conv: dict
    newest: float                 # newest activity, for the cap's newest-first ordering
    item_id: str
    messages: list[dict] = field(default_factory=list)   # DM history, or the thread root
    fetch_replies: bool = False
    unread: bool = False          # a DM with someone else's message after the read position
    last_read: float | None = None   # the conversation's read position, when Slack gave one


def _name_lookup(client, log):
    """user_id -> display name, cached; a failed lookup shows the raw id rather than abort."""
    cache: dict[str, str] = {}

    def name_of(user_id: str) -> str:
        if not user_id:
            return "unknown"
        if user_id not in cache:
            try:
                cache[user_id] = display_name(client.user(user_id))
            except Exception as e:  # noqa: BLE001 - a name is cosmetic
                log(f"  no name for {user_id}: {type(e).__name__}")
                cache[user_id] = user_id
        return cache[user_id]
    return name_of


def _last_read(client, conv: dict) -> float | None:
    """The owner's read position in a conversation, or None when Slack won't say (then only
    the window applies: never guess unread)."""
    try:
        info = client.info(conv["id"])
    except Exception:  # noqa: BLE001 - unread is a widening of the window, never worth failing
        return None
    if info.get("last_read") in (None, ""):
        return None   # documented for DMs only: a channel without one gets the window
    try:
        return float(info["last_read"])
    except (TypeError, ValueError):
        return None


def _thread_last_read(raw: list[dict]) -> float | None:
    """A followed thread's read position, from the parent conversations.replies returns; None
    when the owner does not follow it or Slack leaves it out."""
    parent = raw[0] if raw else {}
    if parent.get("subscribed") is not True or parent.get("last_read") in (None, ""):
        return None
    try:
        return float(parent["last_read"])
    except (TypeError, ValueError):
        return None


# A Slack item id: a DM or group DM ("dm"), or a channel thread by its root's ts.
SLACK_ITEM = re.compile(r"slack:([A-Z0-9]{3,20}):(dm|\d{9,11}\.\d{6})")


def _thread_unread(raw: list[dict], pos: float | None, owner: str) -> bool:
    return pos is not None and any(m.get("user") != owner and float(m.get("ts", 0)) > pos
                                   for m in raw[1:] if not is_system(m))


@dataclass
class Workspace:
    owner: str
    team: str
    host: str
    name_of: object


def workspace(client, log=lambda s: None) -> Workspace:
    me = client.auth_test()
    if not me.get("user_id") or not me.get("team_id"):
        raise SlackError("auth.test", "missing_user_or_team_id")
    host = urlparse(me["url"]).hostname or me.get("team", "")
    return Workspace(me["user_id"], me["team_id"], host, _name_lookup(client, log))


def fetch_one(client, ws: Workspace, item_id: str, floor: float):
    """One Slack conversation by item id, as sync would build it: (item, read position, newest
    ts), or None when it holds nothing real any more. A DM is read back to `floor`. Used for
    threads the owner kept from a search, which sync keeps current like Gmail's kept threads."""
    m = SLACK_ITEM.fullmatch(item_id or "")
    if not m:
        raise ValueError("not a Slack item id")
    channel, rest = m.groups()
    conv = client.info(channel)
    conv.setdefault("id", channel)
    if rest == "dm":
        pos = float(conv["last_read"]) if conv.get("last_read") not in (None, "") else None
        raw = [x for x in client.history(channel, f"{floor:.6f}")
               if x.get("ts") and not is_system(x)]
        if not raw:
            return None
        item = dm_to_item(conv, raw, ws.owner, ws.host, ws.name_of, ws.team)
        if item is not None and pos is not None and any(
                x.get("user") != ws.owner and float(x["ts"]) > pos for x in raw):
            item.labels.append("UNREAD")
    else:
        raw = client.replies(channel, rest)
        if not raw:
            return None
        item = thread_to_item(conv, raw, ws.owner, ws.host, ws.name_of, ws.team)
        pos = _thread_last_read(raw)
        if item is not None and _thread_unread(raw, pos, ws.owner):
            item.labels.append("UNREAD")
    if item is None:
        return None
    return item, pos, max(float(x.get("ts", 0)) for x in raw)


def _apply_local_marks(store: Store, item, pos: float | None, newest: float) -> None:
    """Record Slack's view, then let the owner's FrontDesk marks win until Slack moves on:
    marked unread here stays unread until Slack's read position passes where it was then;
    read here stays read until a newer message arrives."""
    store.set_slack_read(item.id, "" if pos is None else f"{pos:.6f}", f"{newest:.6f}")
    was = store.local_unread_mark(item.id)
    if was is not None and was and pos is not None and pos > float(was):
        store.set_local_unread(item.id, False)          # read in Slack since
    seen = store.local_read(item.id)
    if seen is not None:
        if newest > float(seen):
            with store.tx() as db:                      # a new message: Slack's label stands
                db.execute("DELETE FROM local_read WHERE item_id=?", (item.id,))
        else:
            item.labels[:] = [lb for lb in item.labels if lb != "UNREAD"]


def _candidates(conv: dict, history: list[dict], owner: str, window: float,
                last_read: float | None) -> list[_Candidate]:
    """history runs back to the window's start, or further when the read position is older.
    What came in only because it is unread must be unread: someone else's DM message, or a
    channel message that mentions the owner, after last_read."""
    channel = conv["id"]
    real = [m for m in history if m.get("ts") and not is_system(m)]

    def unread(m: dict) -> bool:
        return last_read is not None and m.get("user") != owner and float(m["ts"]) > last_read
    if conv.get("is_im") or conv.get("is_mpim"):
        is_unread = any(unread(m) for m in real)
        if not real or not (is_unread or any(float(m["ts"]) >= window for m in real)):
            return []
        return [_Candidate(conv, max(float(m["ts"]) for m in real), f"slack:{channel}:dm", real,
                           unread=is_unread, last_read=last_read)]
    out = []
    for m in real:
        # A reply also sent to the channel shows up in history with its root's thread_ts; the
        # root itself is the candidate (when it is in the window), so skip the echo.
        if m.get("thread_ts") and m["thread_ts"] != m["ts"]:
            continue
        replied = owner in (m.get("reply_users") or [])
        started = m.get("user") == owner and bool(m.get("reply_count"))
        if not (replied or started or mentions(m, owner)):
            continue
        if float(m["ts"]) < window and not (mentions(m, owner) and unread(m)):
            continue
        newest = max(float(m["ts"]), float(m.get("latest_reply") or 0))
        out.append(_Candidate(conv, newest, f"slack:{channel}:{m['ts']}", [m],
                              fetch_replies=bool(m.get("reply_count"))))
    return out


def sync(store: Store, settings: dict, token: str, log=print,
         client: SlackClient | None = None) -> SyncResult:
    """One bad conversation (a history error, a missing scope on one channel) is logged and
    skipped so it cannot abort the run; auth and the conversation listing still raise.

    Afterwards, Slack items for this workspace that this run did not produce are pruned (gone
    quiet, aged out of the window, or past the cap). Items of a conversation whose fetch failed
    are kept, so a transient error never empties part of the inbox."""
    client = client or SlackClient(token)
    me = client.auth_test()
    owner = me["user_id"]
    team = me.get("team_id", "")
    if not owner or not team:
        # Keys are slack:<team>:<user>; without both, people could not be keyed or the owner
        # excluded. Refuse the run rather than store guesses.
        raise SlackError("auth.test", "missing_user_or_team_id")
    # item.account stays the workspace HOST: sending checks the token's host against it.
    host = urlparse(me["url"]).hostname or me.get("team", "")
    days = float(settings.get("slack_days", 7))
    cap = int(settings.get("slack_max_items", 100))
    window = time.time() - days * 86400
    # How far back unread may reach: a conversation never read would otherwise mean its whole
    # history.
    floor = time.time() - float(settings.get("slack_unread_days", 90)) * 86400
    name_of = _name_lookup(client, log)

    candidates: list[_Candidate] = []
    failed_channels: set[str] = set()
    for conv in client.list_conversations():
        try:
            last_read = _last_read(client, conv)
            since = window if last_read is None else max(floor, min(window, last_read))
            candidates.extend(_candidates(conv, client.history(conv["id"], f"{since:.6f}"), owner,
                                          window, last_read))
        except Exception as e:  # noqa: BLE001 - isolate per conversation, report the type only
            log(f"  skipped conversation {conv.get('id', '?')}: {type(e).__name__}")
            failed_channels.add(conv.get("id", ""))

    candidates.sort(key=lambda c: c.newest, reverse=True)
    keep: set[str] = set()
    count = changed = 0
    for c in candidates[:cap]:
        keep.add(c.item_id)   # listed: kept even if the build below fails
        try:
            if c.item_id.endswith(":dm"):
                item = dm_to_item(c.conv, c.messages, owner, host, name_of, team)
                if item is not None and c.unread:
                    item.labels.append("UNREAD")
                pos = c.last_read
            else:
                raw = (client.replies(c.conv["id"], c.messages[0]["ts"])
                       if c.fetch_replies else c.messages)
                item = thread_to_item(c.conv, raw, owner, host, name_of, team)
                pos = _thread_last_read(raw)
                if item is not None and _thread_unread(raw, pos, owner):
                    item.labels.append("UNREAD")
        except Exception as e:  # noqa: BLE001 - isolate per item, report the type only
            log(f"  skipped {c.item_id}: {type(e).__name__}")
            continue
        if item is None:
            continue
        _apply_local_marks(store, item, pos, c.newest)
        changed += store.upsert_item(item)
        count += 1
    if len(candidates) > cap:
        log(f"  kept the newest {cap} of {len(candidates)} Slack conversations (slack_max_items)")

    # Conversations the owner kept from a search sit outside the window: fetch them too, so new
    # replies show, and keep them through prune until they are marked done.
    ws = Workspace(owner, team, host, name_of)
    for kid in sorted(store.kept_ids("slack") - keep):
        keep.add(kid)   # listed: kept even if the fetch below fails
        try:
            got = fetch_one(client, ws, kid, floor)
        except Exception as e:  # noqa: BLE001 - isolate per item, report the type only
            log(f"  skipped kept {kid}: {type(e).__name__}")
            continue
        if got is None:
            continue
        item, pos, newest = got
        _apply_local_marks(store, item, pos, newest)
        changed += store.upsert_item(item)
        count += 1

    if failed_channels:
        keep |= {r["id"] for r in store.db.execute("SELECT id FROM items WHERE source='slack'")
                 if r["id"].split(":")[1] in failed_channels}
    removed = store.prune("slack", host, keep)
    if removed:
        log(f"  removed {removed} Slack item(s) no longer active in the last {days:g} days "
            "or unread")
    linked = store.link_slack_names()
    if linked["linked"]:
        log(f"  linked {len(linked['linked'])} Slack name(s) in your notes to Slack users")
    return SyncResult(count, removed, changed)
