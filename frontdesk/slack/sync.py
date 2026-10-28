"""Pull recent Slack DMs and the channel threads that involve the owner into the store.

What counts as involving the owner in a channel: a thread or top-level message in the window
that @-mentions them, or a thread in the window they replied in (thread roots carry
reply_users, so this needs no per-thread fetch to decide). Everything else in a channel is
background and stays out. Upsert by id makes a re-run idempotent, as for Gmail."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

from ..gmail.sync import SyncResult
from ..store import Store
from .client import SlackClient
from .normalize import display_name, dm_to_item, is_system, mentions, thread_to_item


@dataclass
class _Candidate:
    conv: dict
    newest: float                 # newest activity, for the cap's newest-first ordering
    item_id: str
    messages: list[dict] = field(default_factory=list)   # DM history, or the thread root
    fetch_replies: bool = False


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


def _candidates(conv: dict, history: list[dict], owner: str) -> list[_Candidate]:
    channel = conv["id"]
    real = [m for m in history if m.get("ts") and not is_system(m)]
    if conv.get("is_im") or conv.get("is_mpim"):
        if not real:
            return []
        return [_Candidate(conv, max(float(m["ts"]) for m in real), f"slack:{channel}:dm", real)]
    out = []
    for m in real:
        # A reply also sent to the channel shows up in history with its root's thread_ts; the
        # root itself is the candidate (when it is in the window), so skip the echo.
        if m.get("thread_ts") and m["thread_ts"] != m["ts"]:
            continue
        replied = owner in (m.get("reply_users") or [])
        if not (replied or mentions(m, owner)):
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
    host = urlparse(me["url"]).hostname or me.get("team", "")
    days = float(settings.get("slack_days", 7))
    cap = int(settings.get("slack_max_items", 60))
    oldest = f"{time.time() - days * 86400:.6f}"
    name_of = _name_lookup(client, log)

    candidates: list[_Candidate] = []
    failed_channels: set[str] = set()
    for conv in client.list_conversations():
        try:
            candidates.extend(_candidates(conv, client.history(conv["id"], oldest), owner))
        except Exception as e:  # noqa: BLE001 - isolate per conversation, report the type only
            log(f"  skipped conversation {conv.get('id', '?')}: {type(e).__name__}")
            failed_channels.add(conv.get("id", ""))

    candidates.sort(key=lambda c: c.newest, reverse=True)
    keep: set[str] = set()
    count = 0
    for c in candidates[:cap]:
        keep.add(c.item_id)   # listed: kept even if the build below fails
        try:
            if c.item_id.endswith(":dm"):
                item = dm_to_item(c.conv, c.messages, owner, host, name_of)
            else:
                raw = (client.replies(c.conv["id"], c.messages[0]["ts"])
                       if c.fetch_replies else c.messages)
                item = thread_to_item(c.conv, raw, owner, host, name_of)
        except Exception as e:  # noqa: BLE001 - isolate per item, report the type only
            log(f"  skipped {c.item_id}: {type(e).__name__}")
            continue
        if item is None:
            continue
        store.upsert_item(item)
        count += 1
    if len(candidates) > cap:
        log(f"  kept the newest {cap} of {len(candidates)} Slack conversations (slack_max_items)")

    if failed_channels:
        keep |= {r["id"] for r in store.db.execute("SELECT id FROM items WHERE source='slack'")
                 if r["id"].split(":")[1] in failed_channels}
    removed = store.prune("slack", host, keep)
    if removed:
        log(f"  removed {removed} Slack item(s) no longer active in the last {days:g} days")
    return SyncResult(count, removed)
