"""Search all of the owner's Gmail (archived mail too) with Gmail's own query language, read-only.

Results are rows for the page, never stored and never ranked: nothing here writes the store or
calls a model. Each row comes from a metadata fetch (headers and labels, no bodies). Every field
except the thread id and dates is text the sender chose, so the page renders it as text only."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from email.utils import parseaddr
from urllib.parse import quote

from .client import GmailClient
from .normalize import _headers

SEARCH_LIMIT = 20
MAX_QUERY_CHARS = 500


def _iso(ms: str | int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def thread_row(thread: dict, account: str) -> dict | None:
    """One result row from a metadata-format thread, or None when every message is a draft."""
    msgs = [m for m in thread.get("messages", []) if "DRAFT" not in (m.get("labelIds") or [])]
    if not msgs:
        return None
    msgs.sort(key=lambda m: int(m.get("internalDate", 0)))
    first, last = _headers(msgs[0].get("payload", {})), _headers(msgs[-1].get("payload", {}))
    labels = sorted({lb for m in msgs for lb in (m.get("labelIds") or [])})
    tid = thread["id"]
    return {
        "id": f"gmail:{tid}",
        "subject": first.get("subject", ""),
        "sender": last.get("from", ""),
        "from_me": parseaddr(last.get("from", ""))[1].lower() == account.lower(),
        "updated_at": _iso(msgs[-1].get("internalDate", 0)),
        "messages": len(msgs),
        "in_inbox": "INBOX" in labels,
        "unread": "UNREAD" in labels,
        "url": f"https://mail.google.com/mail/?authuser={quote(account, safe='@')}#all/{tid}",
    }


SEARCH_WORKERS = 8   # measured on a real 20-result search: 4 s serial, 1.2 s with 4, 0.85 s with 8


def search(gmail: GmailClient, query: str, limit: int = SEARCH_LIMIT,
           workers: int = SEARCH_WORKERS) -> list[dict]:
    """Up to `limit` threads matching `query` across all mail, newest first (Gmail's order).
    The metadata fetches run in a small pool, each worker on its own client (gmail.clone()),
    which takes a 20-result search from about 4 s to under 1 s; 20 fetches at 40 quota units
    each stay far under Gmail's 6,000 a minute. Any failed fetch fails the search, loudly."""
    account = gmail.profile_email()   # also refreshes the token once, before the workers share it
    ids = gmail.list_thread_ids(query, limit)
    local = threading.local()

    def fetch(tid: str) -> dict:
        if not hasattr(local, "client"):
            local.client = gmail.clone() if hasattr(gmail, "clone") else gmail
        return local.client.get_thread(tid, fmt="metadata")

    if workers <= 1 or len(ids) <= 1 or not hasattr(gmail, "clone"):
        threads = [gmail.get_thread(tid, fmt="metadata") for tid in ids]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            threads = list(pool.map(fetch, ids))   # keeps Gmail's order
    return [row for row in (thread_row(t, account) for t in threads) if row]


def fetch_item(gmail: GmailClient, thread_id: str, inline_images: bool = False):
    """The whole thread as an Item (None when it holds only drafts). For a preview nothing is
    stored; keeping a thread also fetches its inline images, as sync does."""
    from .normalize import thread_to_item
    from .sync import fetch_inline_images
    thread = gmail.get_thread(thread_id)
    if inline_images:
        fetch_inline_images(gmail, thread)
    return thread_to_item(thread, gmail.profile_email())
