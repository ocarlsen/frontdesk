"""Slack conversation JSON -> Item. Pure and offline so it is fully testable on synthetic
fixtures: user names come in through a name_of(user_id) callable rather than API calls.

Two shapes become Items: a DM or group DM (all its recent messages are ONE item, since DMs
rarely use threads), and a channel thread or lone channel message. Slack's markup (<@U1>,
<#C1|name>, <url|label>, &amp;) is rewritten into plain readable text, and system events
(joins, topic changes, pins) are dropped, since neither helps the model or the owner."""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from datetime import UTC, datetime

from ..gmail.normalize import BODY_CAP, TRUNCATED
from ..items import Item, Message

NameOf = Callable[[str], str]

MAX_MESSAGES = 50     # per item; a busy DM keeps its newest (a thread keeps its root too)
SUBJECT_CAP = 80
# Subtypes that carry something a person (or bot) said. Everything else is a system event:
# channel_join/leave, topic/purpose/name changes, pins, archive, tombstones, huddles, ...
_KEPT_SUBTYPES = {"", "bot_message", "thread_broadcast", "file_share", "me_message"}
_MARKUP = re.compile(r"<([^<>]+)>")


def display_name(user: dict) -> str:
    """The name Slack shows: the profile display name, else the real name, else the handle."""
    prof = user.get("profile") or {}
    return (prof.get("display_name") or prof.get("real_name") or user.get("real_name")
            or user.get("name") or user.get("id") or "unknown")


def readable(text: str, name_of: NameOf) -> str:
    """Slack mrkdwn markup -> plain text. Markup is rewritten BEFORE entities are unescaped,
    so a literal '&lt;@U1&gt;' typed by a person stays text instead of becoming a mention."""
    def sub(m: re.Match) -> str:
        target, _, label = m.group(1).partition("|")
        if target.startswith("@"):
            return "@" + name_of(target[1:])
        if target.startswith("#"):
            return "#" + (label or target[1:])
        if target.startswith("!"):      # <!here>, <!channel>, <!subteam^S1|@team>, <!date^..|x>
            return label or "@" + target[1:].split("^")[0]
        if target.startswith("mailto:"):
            target = target[len("mailto:"):]
        if label and label != target:
            return f"{label} ({target})"
        return target
    out = _MARKUP.sub(sub, text or "")
    return out.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def is_system(m: dict) -> bool:
    return (m.get("subtype") or "") not in _KEPT_SUBTYPES


def is_bot(m: dict) -> bool:
    return m.get("subtype") == "bot_message" or bool(m.get("bot_id"))


def mentions(m: dict, user_id: str) -> bool:
    text = m.get("text") or ""
    return f"<@{user_id}>" in text or f"<@{user_id}|" in text


def iso(ts: str) -> str:
    return datetime.fromtimestamp(float(ts), tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def permalink(host: str, channel: str, ts: str, thread_ts: str = "") -> str:
    url = f"https://{host}/archives/{channel}/p{ts.replace('.', '')}"
    return url + (f"?thread_ts={thread_ts}&cid={channel}" if thread_ts else "")


def sender_name(m: dict, name_of: NameOf) -> str:
    if is_bot(m):
        name = ((m.get("bot_profile") or {}).get("name") or m.get("username")
                or (name_of(m["user"]) if m.get("user") else "") or "bot")
        return f"{name} (bot)"
    return name_of(m.get("user", ""))


def to_message(m: dict, owner_id: str, name_of: NameOf) -> Message | None:
    """None for system events. Attached files show as '[file: name]' so a file-only message
    is not an empty body."""
    if is_system(m):
        return None
    body = readable(m.get("text", ""), name_of).strip()
    files = [f"[file: {f.get('name') or f.get('title') or 'file'}]"
             for f in m.get("files") or []]
    body = "\n".join([body, *files] if body else files)
    if len(body) > BODY_CAP:
        body = body[:BODY_CAP] + TRUNCATED
    return Message(sender=sender_name(m, name_of), sent_at=iso(m["ts"]), body=body,
                   is_mine=bool(owner_id) and m.get("user") == owner_id, html="")


def _ordered(raw: Iterable[dict]) -> list[dict]:
    """Oldest first, one per ts (paged replies can repeat the root), system events dropped."""
    seen: dict[str, dict] = {}
    for m in raw:
        if m.get("ts") and not is_system(m):
            seen.setdefault(m["ts"], m)
    return sorted(seen.values(), key=lambda m: float(m["ts"]))


def _participants(messages: list[Message]) -> list[str]:
    out: list[str] = []
    for msg in messages:
        if msg.sender not in out:
            out.append(msg.sender)
    return out


def _mpdm_handles(name: str) -> list[str]:
    """'mpdm-ann--bo--cy-1' -> ['ann', 'bo', 'cy']: Slack's own name for a group DM."""
    if not name.startswith("mpdm-"):
        return []
    return [h for h in re.sub(r"-\d+$", "", name[len("mpdm-"):]).split("--") if h]


def dm_to_item(conv: dict, raw: Iterable[dict], owner_id: str, host: str,
               name_of: NameOf) -> Item | None:
    """A DM or group DM as one item. None when nothing in it is a real message."""
    msgs = _ordered(raw)[-MAX_MESSAGES:]
    messages = [to_message(m, owner_id, name_of) for m in msgs]
    if not messages:
        return None
    channel = conv["id"]
    participants = _participants(messages)
    if conv.get("is_im"):
        subject = f"Slack DM with {name_of(conv.get('user', ''))}"
        kind = "dm"
    else:
        me = name_of(owner_id)
        others = [p for p in participants if p != me] or _mpdm_handles(conv.get("name", ""))
        subject = f"Slack group DM: {', '.join(others)}"
        kind = "group_dm"
    return Item(
        id=f"slack:{channel}:dm",
        source="slack",
        account=host,
        subject=subject,
        participants=participants,
        messages=messages,
        updated_at=messages[-1].sent_at,
        labels=["slack", kind],
        url=permalink(host, channel, msgs[-1]["ts"]),
    )


def _first_line(text: str) -> str:
    for line in text.split("\n"):
        if line.strip():
            return line.strip()[:SUBJECT_CAP].rstrip()
    return "(no text)"


def thread_to_item(conv: dict, raw: Iterable[dict], owner_id: str, host: str,
                   name_of: NameOf) -> Item | None:
    """A channel thread (root + replies) or a lone channel message. The root is the message
    whose ts is the thread's ts; the newest replies are kept when the thread is long."""
    msgs = _ordered(raw)
    if not msgs:
        return None
    root = msgs[0]
    root_ts = root.get("thread_ts") or root["ts"]
    if len(msgs) > MAX_MESSAGES:
        msgs = [root, *msgs[-(MAX_MESSAGES - 1):]]
    messages = [to_message(m, owner_id, name_of) for m in msgs]
    channel = conv["id"]
    threaded = len(msgs) > 1 or bool(root.get("reply_count"))
    return Item(
        id=f"slack:{channel}:{root_ts}",
        source="slack",
        account=host,
        subject=f"#{conv.get('name', channel)}: {_first_line(messages[0].body)}",
        participants=_participants(messages),
        messages=messages,
        updated_at=messages[-1].sent_at,
        labels=["slack", "channel"],
        url=permalink(host, channel, root_ts, root_ts if threaded else ""),
    )
