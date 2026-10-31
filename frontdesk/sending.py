"""Send, in four steps, each enforced here rather than in the page:

1. prepare: the owner's exact text plus recipients, subject and threading DERIVED FROM THE THREAD
   (never from the body or the model) become a stored, immutable message. Refused while
   [placeholders] remain, if a new message arrived since the page loaded the thread, on an
   account mismatch, or over the rate limits.
2. confirm: the owner has seen exactly that message on the confirm screen; it is queued to go out
   UNDO_SECONDS later.
3. cancel: possible until the dispatcher picks it up. After that Gmail has it; there is no recall.
4. dispatch (the server's background loop): sends due messages. A new message in the thread
   since prepare, or a queue entry far past its time (the server was down), stops it. The send
   call is never retried: a timeout is recorded as 'unknown', for the owner to check in Gmail.

Every state is a row in the actions table: prepared -> queued -> sending -> sent, or cancelled,
stale, expired, failed, unknown."""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from email.utils import parseaddr
from urllib.parse import urlparse

import requests

from . import drafting
from .actions import (
    _CLIENT_KEY,
    _PLACEHOLDER,
    MAX_DRAFT_CHARS,
    ActionError,
    _check_account,
    _native_id,
)
from .gmail.client import GmailClient, GmailError
from .slack.client import SlackError
from .store import Store

UNDO_SECONDS = 30
STALE_AFTER = timedelta(minutes=10)     # queued this long past due: expire instead of sending
MAX_PER_HOUR = 10
PER_THREAD_GAP = timedelta(minutes=10)
LIVE = ("queued", "sending", "sent", "unknown")


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _check_limits(store: Store, item_id: str, now: datetime) -> None:
    rows = store.db.execute("SELECT item_id, created_at, status FROM actions WHERE kind='send'")
    recent = [r for r in rows if r["status"] in LIVE]
    if sum(_parse(r["created_at"]) > now - timedelta(hours=1) for r in recent) >= MAX_PER_HOUR:
        raise ActionError(f"send limit reached ({MAX_PER_HOUR} an hour)")
    if any(r["item_id"] == item_id and _parse(r["created_at"]) > now - PER_THREAD_GAP
           for r in recent):
        raise ActionError("a reply to this thread went out in the last 10 minutes")


def _payload(row) -> dict:
    return json.loads(row["payload"])


def _slack_target(item) -> tuple[str, str | None, str]:
    """(channel, thread_ts or None, label) from a Slack item id 'slack:<channel>:<ts|dm>'."""
    _, channel, ts = item.id.split(":", 2)
    if ts == "dm":
        return channel, None, item.subject.replace("Slack DM with ", "DM: ")
    return channel, ts, item.subject.split(":", 1)[0] + " (thread)"


def prepare(store: Store, item_id: str, body: str, seen_updated_at: str,
            gmail: GmailClient | None, client_key: str, now: datetime | None = None,
            slack=None) -> dict:
    now = now or _now()
    if not _CLIENT_KEY.fullmatch(client_key or ""):
        raise ActionError("missing or malformed idempotency key")
    if not isinstance(body, str) or not body.strip():
        raise ActionError("the reply is empty")
    if len(body) > MAX_DRAFT_CHARS:
        raise ActionError("the reply is too long")
    if _PLACEHOLDER.search(body):
        raise ActionError("fill in the [bracketed] parts first")
    item = store.get_item(item_id)
    if item is None:
        raise ActionError("unknown thread (it may have been synced away)")
    if item.updated_at != seen_updated_at:
        raise ActionError("a new message arrived in this thread; reload before sending")
    key = f"send:{item_id}:{client_key}"
    prior = store.action(key)
    if prior is not None:
        if prior["status"] == "prepared":
            p = _payload(prior)
            return {"action_id": prior["id"], **{k: p[k] for k in ("to", "cc", "subject")},
                    "body": body}
        raise ActionError("this send was already handled; reload")
    _check_limits(store, item_id, now)
    sha = hashlib.sha256(body.encode()).hexdigest()
    if item.source == "slack" and (slack is not None or gmail is not None):
        if slack is None:
            raise ActionError("Slack is not connected (no user token)")
        host = urlparse(slack.auth_test().get("url", "")).hostname or ""
        if host != item.account:
            raise ActionError(f"the Slack token is for {host}, but this thread is in "
                              f"{item.account}")
        channel, thread_ts, label = _slack_target(item)
        p = {"source": "slack", "channel": channel, "thread_ts": thread_ts, "text": body,
             "to": [label], "cc": [], "subject": item.subject, "body_sha256": sha,
             "seen_updated_at": seen_updated_at}
    elif gmail is None and item.source == "slack":   # demo: shown like a Slack send, posts nothing
        p = {"demo": True, "to": [_slack_target(item)[2]], "cc": [], "subject": item.subject,
             "body_sha256": sha, "seen_updated_at": seen_updated_at}
    elif gmail is None:   # demo: derive the visible recipient from the stored thread, send nothing
        inbound = [m for m in item.messages if not m.is_mine]
        to = [parseaddr(inbound[-1].sender)[1]] if inbound else []
        p = {"demo": True, "to": to, "cc": [], "subject": "Re: " + item.subject,
             "body_sha256": sha, "seen_updated_at": seen_updated_at}
    else:
        _check_account(gmail, item.account)
        try:
            msg, ctx = drafting.build_reply(gmail, _native_id(item_id), body)
        except drafting.DraftError as e:
            raise ActionError(str(e)) from e
        p = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode(),
             "thread_id": ctx["thread_id"], "to": ctx["to"], "cc": ctx["cc"],
             "subject": ctx["subject"], "body_sha256": sha, "seen_updated_at": seen_updated_at}
    from .usage import origin_of
    p["origin"] = origin_of(store, item, body)   # for the usage log; the verdict, not the text
    p["source_kind"] = item.source
    action_id = store.begin_action(key, item_id, "send", {})
    store.finish_action(action_id, "prepared", p)
    return {"action_id": action_id, "to": p["to"], "cc": p["cc"], "subject": p["subject"],
            "body": body, "demo": bool(p.get("demo"))}


def _row(store: Store, action_id: int):
    row = store.db.execute("SELECT * FROM actions WHERE id=? AND kind='send'",
                           (action_id,)).fetchone()
    if row is None:
        raise ActionError("unknown send")
    return row


def confirm(store: Store, action_id: int, now: datetime | None = None) -> dict:
    now = now or _now()
    row = _row(store, action_id)
    if row["status"] != "prepared":
        raise ActionError(f"this send is {row['status']}, not awaiting confirmation")
    p = _payload(row)
    item = store.get_item(row["item_id"])
    if item is None or item.updated_at != p["seen_updated_at"]:
        store.finish_action(action_id, "stale", p)
        raise ActionError("a new message arrived in this thread; reload before sending")
    p["send_at"] = _iso(now + timedelta(seconds=UNDO_SECONDS))
    store.finish_action(action_id, "queued", p)   # demo too, so Undo behaves the same
    return {"status": "queued", "send_at": p["send_at"], "undo_seconds": UNDO_SECONDS,
            "demo": bool(p.get("demo"))}


def cancel(store: Store, action_id: int) -> dict:
    with store.tx() as db:   # one statement: only a still-queued send can be cancelled
        cur = db.execute("UPDATE actions SET status='cancelled' WHERE id=? AND kind='send' "
                         "AND status IN ('queued', 'prepared')", (action_id,))
    if cur.rowcount != 1:
        raise ActionError(f"too late to cancel: this send is {_row(store, action_id)['status']}")
    return {"status": "cancelled"}


def status(store: Store, action_id: int) -> dict:
    row = _row(store, action_id)
    p = _payload(row)
    return {"status": row["status"], "send_at": p.get("send_at", "")}


def dispatch_due(store: Store, gmail_factory, now: datetime | None = None,
                 slack_factory=None) -> list[tuple]:
    """Send every queued message whose undo window has passed. Returns (action_id, status)."""
    now = now or _now()
    out = []
    due = store.db.execute("SELECT * FROM actions WHERE kind='send' AND status='queued'")
    for row in due:
        p = _payload(row)
        if _parse(p["send_at"]) > now:
            continue
        with store.tx() as db:   # claim it: a concurrent cancel or second loop loses here
            claimed = db.execute("UPDATE actions SET status='sending' WHERE id=? "
                                 "AND status='queued'", (row["id"],)).rowcount == 1
        if not claimed:
            continue
        item = store.get_item(row["item_id"])
        if p.get("demo"):
            result = "demo"                      # never reaches Gmail; never recorded as sent
        elif now - _parse(p["send_at"]) > STALE_AFTER:
            result = "expired"
        elif item is None or item.updated_at != p["seen_updated_at"]:
            result = "stale"
        else:
            try:
                if p.get("source") == "slack":
                    if slack_factory is None:
                        raise SlackError("chat.postMessage", "not_connected")
                    sent = slack_factory().post_message(p["channel"], p["text"],
                                                        p.get("thread_ts"))
                    p["slack_ts"] = sent.get("ts", "")
                else:
                    sent = gmail_factory().send_message(p["raw"], p["thread_id"])
                    p["gmail_id"] = sent.get("id", "")
                result = "sent"
            except (GmailError, SlackError):
                result = "failed"
            except requests.RequestException:
                result = "unknown"   # it may have gone out; never resend blindly
        store.finish_action(row["id"], result, p)
        if result == "sent":
            store.log_usage("send", source=p.get("source_kind", p.get("source", "")),
                            origin=p.get("origin", ""))
        out.append((row["id"], result))
    return out
