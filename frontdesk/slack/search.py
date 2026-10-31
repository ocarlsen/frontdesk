"""Search all of the owner's Slack with Slack's own query language (search.messages, read-only).
Results are rows for the page, never stored and never ranked: nothing here writes the store or
calls a model. Message text and names are what others wrote, so the page renders them as text."""
from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from .normalize import plain_mrkdwn, readable

SLACK_LIMIT = 20
SNIPPET_CHARS = 400


def _iso(ts: str) -> str:
    try:
        return datetime.fromtimestamp(float(ts), tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return ""


def match_row(m: dict) -> dict | None:
    """One result row; its id is the id FrontDesk gives the same conversation when it syncs it
    (a DM or group DM is one item; a channel message belongs to its thread's root)."""
    ch = m.get("channel") or {}
    cid, ts = ch.get("id", ""), m.get("ts", "")
    if not cid or not ts:
        return None
    link = m.get("permalink", "")
    root = (parse_qs(urlparse(link).query).get("thread_ts") or [""])[0] or ts
    if ch.get("is_im"):
        kind, label, item_id = "dm", "Direct message", f"slack:{cid}:dm"
    elif ch.get("is_mpim"):
        kind, label, item_id = "group_dm", "Group DM", f"slack:{cid}:dm"
    else:
        kind, label, item_id = "channel", "#" + (ch.get("name") or cid), f"slack:{cid}:{root}"
    text = plain_mrkdwn(readable(m.get("text") or "", lambda uid: uid)).strip()
    if len(text) > SNIPPET_CHARS:
        text = text[:SNIPPET_CHARS].rstrip() + "…"
    return {"id": item_id, "kind": kind, "where": label,
            "sender": m.get("username") or m.get("user") or "",
            "text": text, "updated_at": _iso(ts),
            "url": link if link.startswith("https://") and ".slack.com/" in link else ""}


def search(slack, query: str, limit: int = SLACK_LIMIT) -> list[dict]:
    """Up to `limit` matching messages, newest first, one row per message."""
    return [r for r in (match_row(m) for m in slack.search_messages(query, limit)) if r]
