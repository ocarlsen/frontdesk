"""Slack conversation JSON -> Item. Pure and offline so it is fully testable on synthetic
fixtures: user names come in through a name_of(user_id) callable rather than API calls.

Two shapes become Items: a DM or group DM (all its recent messages are ONE item, since DMs
rarely use threads), and a channel thread or lone channel message. Slack's markup (<@U1>,
<#C1|name>, <url|label>, &amp;) is rewritten into plain readable text, and system events
(joins, topic changes, pins) are dropped, since neither helps the model or the owner.

People are keyed by stable IDs, not display names (a rename would orphan a note, and two people
with one name would share one): a user is "slack:<team_id>:<user_id>", a bot or app
"slack:<team_id>:bot:<bot_id>", both lowercase like every stored address. Each message keeps the
display name in `sender` and the key in `sender_key`; the item's `names` maps keys to display
names for the page. Bots are not participants: notes and related threads are about people, and a
bot that posts in every deploy thread would otherwise make unrelated threads look related."""
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


# Slack's :shortcodes: for the emoji that turn up in work chat, as the characters Slack shows.
# A code not listed stays as typed (never dropped: it may be a custom emoji worth seeing).
EMOJI = {
    "incoming_envelope": "\U0001F4E8", "envelope": "\u2709\ufe0f", "email": "\U0001F4E7",
    "white_check_mark": "\u2705", "heavy_check_mark": "\u2714\ufe0f", "x": "\u274C",
    "warning": "\u26A0\ufe0f", "rotating_light": "\U0001F6A8", "mag": "\U0001F50D",
    "ocean": "\U0001F30A", "tada": "\U0001F389", "rocket": "\U0001F680", "fire": "\U0001F525",
    "eyes": "\U0001F440", "thumbsup": "\U0001F44D", "+1": "\U0001F44D", "-1": "\U0001F44E",
    "thumbsdown": "\U0001F44E", "pray": "\U0001F64F", "clap": "\U0001F44F", "wave": "\U0001F44B",
    "smile": "\U0001F604", "slightly_smiling_face": "\U0001F642", "joy": "\U0001F602",
    "thinking_face": "\U0001F914", "heart": "\u2764\ufe0f", "memo": "\U0001F4DD",
    "calendar": "\U0001F4C6", "date": "\U0001F4C5", "clock3": "\U0001F552",
    "hourglass": "\u231B", "bell": "\U0001F514", "pushpin": "\U0001F4CC",
    "link": "\U0001F517", "lock": "\U0001F512", "key": "\U0001F511", "bulb": "\U0001F4A1",
    "chart_with_upwards_trend": "\U0001F4C8", "moneybag": "\U0001F4B0", "dollar": "\U0001F4B5",
    "package": "\U0001F4E6", "inbox_tray": "\U0001F4E5", "outbox_tray": "\U0001F4E4",
    "handshake": "\U0001F91D", "house": "\U0001F3E0", "robot_face": "\U0001F916",
    "large_green_circle": "\U0001F7E2", "large_yellow_circle": "\U0001F7E1",
    "red_circle": "\U0001F534", "black_circle": "\u26AB", "point_right": "\U0001F449",
    "question": "\u2753", "exclamation": "\u2757", "no_entry": "\u26D4",
    "construction": "\U0001F6A7", "sparkles": "\u2728", "star": "\u2B50",
}
_EMOJI_CODE = re.compile(r":([a-z][a-z0-9_+\-]*):")


def emojize(text: str) -> str:
    return _EMOJI_CODE.sub(lambda m: EMOJI.get(m.group(1), m.group(0)), text or "")


_MRKDWN = (re.compile(r"```\n?(.*?)\n?```", re.S), re.compile(r"`([^`\n]+)`"),
           re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])"),
           re.compile(r"(?<![\w_])_([^_\n]+)_(?![\w_])"),
           re.compile(r"(?<![\w~])~([^~\n]+)~(?![\w~])"))


def plain_mrkdwn(text: str) -> str:
    """*bold*, _italic_, ~strike~ and `code` markers removed, the words kept: for a one-line
    snippet, where the markers are noise. (Synced messages keep them; the model reads them.)"""
    for rx in _MRKDWN:
        text = rx.sub(r"\1", text)
    return text


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
    return emojize(out.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"))


def is_system(m: dict) -> bool:
    return (m.get("subtype") or "") not in _KEPT_SUBTYPES


def is_bot(m: dict) -> bool:
    return m.get("subtype") == "bot_message" or bool(m.get("bot_id"))


def user_key(team: str, user_id: str) -> str:
    """The participant key of a Slack user: 'slack:<team_id>:<user_id>', lowercase."""
    return f"slack:{team}:{user_id}".lower()


def bot_key(team: str, bot_id: str) -> str:
    return f"slack:{team}:bot:{bot_id}".lower()


def sender_key(m: dict, team: str) -> str:
    """The stable key of who sent `m`: a bot by its bot_id (an app message may also carry the
    user who installed it), a person by user id; '' when Slack gives neither."""
    if is_bot(m):
        if m.get("bot_id"):
            return bot_key(team, m["bot_id"])
        return user_key(team, m["user"]) if m.get("user") else ""
    return user_key(team, m["user"]) if m.get("user") else ""


def _team(team: str) -> str:
    if not isinstance(team, str) or not team.strip():
        # A key without a workspace would collide across workspaces: refuse, never guess.
        raise ValueError("Slack items need the workspace's team id (auth.test team_id)")
    return team.strip()


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


def to_message(m: dict, owner_id: str, name_of: NameOf, team: str) -> Message | None:
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
                   is_mine=bool(owner_id) and m.get("user") == owner_id,
                   html="", sender_key=sender_key(m, _team(team)))


def _ordered(raw: Iterable[dict]) -> list[dict]:
    """Oldest first, one per ts (paged replies can repeat the root), system events dropped."""
    seen: dict[str, dict] = {}
    for m in raw:
        if m.get("ts") and not is_system(m):
            seen.setdefault(m["ts"], m)
    return sorted(seen.values(), key=lambda m: float(m["ts"]))


def _participants(messages: list[Message]) -> list[str]:
    """The people who wrote in it, as keys, first appearance first. Bots are left out (see the
    module docstring); so is a message Slack gave no sender for."""
    out: list[str] = []
    for msg in messages:
        k = msg.sender_key
        if k and ":bot:" not in k and k not in out:
            out.append(k)
    return out


def _names(messages: list[Message], extra: dict[str, str]) -> dict[str, str]:
    """{key: display name} for the page: each sender as their newest message shows them, plus
    `extra` (the owner, the other side of a DM)."""
    out = dict(extra)
    for msg in messages:
        if msg.sender_key:
            out[msg.sender_key] = msg.sender
    return out


def _mpdm_handles(name: str) -> list[str]:
    """'mpdm-ann--bo--cy-1' -> ['ann', 'bo', 'cy']: Slack's own name for a group DM."""
    if not name.startswith("mpdm-"):
        return []
    return [h for h in re.sub(r"-\d+$", "", name[len("mpdm-"):]).split("--") if h]


def dm_to_item(conv: dict, raw: Iterable[dict], owner_id: str, host: str,
               name_of: NameOf, team: str) -> Item | None:
    """A DM or group DM as one item. None when nothing in it is a real message. Subjects are
    built from display names, never keys."""
    team = _team(team)
    msgs = _ordered(raw)[-MAX_MESSAGES:]
    messages = [to_message(m, owner_id, name_of, team) for m in msgs]
    if not messages:
        return None
    channel = conv["id"]
    participants = _participants(messages)
    me = user_key(team, owner_id) if owner_id else ""
    extra = {me: name_of(owner_id)} if me else {}
    if conv.get("is_im"):
        subject = f"Slack DM with {name_of(conv.get('user', ''))}"
        kind = "dm"
        if conv.get("user"):
            extra[user_key(team, conv["user"])] = name_of(conv["user"])
    else:
        kind = "group_dm"
    names = _names(messages, extra)
    if kind == "group_dm":
        others = [names[p] for p in participants if p != me] \
            or _mpdm_handles(conv.get("name", ""))
        subject = f"Slack group DM: {', '.join(others)}"
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
        names=names,
        owner_key=me,
    )


def _first_line(text: str) -> str:
    for line in text.split("\n"):
        if line.strip():
            return line.strip()[:SUBJECT_CAP].rstrip()
    return "(no text)"


def thread_to_item(conv: dict, raw: Iterable[dict], owner_id: str, host: str,
                   name_of: NameOf, team: str) -> Item | None:
    """A channel thread (root + replies) or a lone channel message. The root is the message
    whose ts is the thread's ts; the newest replies are kept when the thread is long."""
    team = _team(team)
    msgs = _ordered(raw)
    if not msgs:
        return None
    root = msgs[0]
    root_ts = root.get("thread_ts") or root["ts"]
    if len(msgs) > MAX_MESSAGES:
        msgs = [root, *msgs[-(MAX_MESSAGES - 1):]]
    messages = [to_message(m, owner_id, name_of, team) for m in msgs]
    channel = conv["id"]
    threaded = len(msgs) > 1 or bool(root.get("reply_count"))
    me = user_key(team, owner_id) if owner_id else ""
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
        names=_names(messages, {me: name_of(owner_id)} if me else {}),
        owner_key=me,
    )
