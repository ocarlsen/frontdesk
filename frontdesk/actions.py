"""Actions on mail. Every action follows one shape:

1. resolve the item from the store (never from client-supplied fields);
2. write a PENDING row keyed by the client's per-click idempotency key first, so a double-click,
   a retry or a crash cannot repeat the side effect unnoticed; a request whose effect already
   holds (archiving a thread that is already archived) is a no-op;
3. call Gmail with the separate actions token (`frontdesk authorize-actions`), after checking it
   belongs to the same account as the item;
4. record done or failed.

Archive removes the INBOX label: reversible, and Undo adds it back. Save draft creates a Gmail
draft in the thread from the text the owner sees in the box (never the model's text unedited
by the page, never recipients from the body); it refuses if a new message arrived since the page
loaded the thread. In demo mode (gmail=None) the store side runs and Gmail is skipped, so the
flow is visible without an account."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3

import requests

from . import drafting
from .gmail.client import GmailClient, GmailError
from .store import Store


class ActionError(Exception):
    """Shown to the owner as-is; never carries mail content."""


def _native_id(item_id: str) -> str:
    source, _, native = item_id.partition(":")
    if source != "gmail" or not native:
        raise ActionError(f"not a Gmail thread: {item_id}")
    return native


def _check_account(gmail: GmailClient, account: str) -> None:
    owner = gmail.profile_email().lower()
    if owner != account.lower():
        raise ActionError(f"the actions token is for {owner}, but this thread is in {account}")


_CLIENT_KEY = re.compile(r"[A-Za-z0-9-]{8,64}")


def set_archived(store: Store, item_id: str, archived: bool, gmail: GmailClient | None,
                 client_key: str) -> dict:
    if not _CLIENT_KEY.fullmatch(client_key or ""):
        raise ActionError("missing or malformed idempotency key")
    item = store.get_item(item_id)
    if item is None:
        raise ActionError("unknown thread (it may have been synced away)")
    kind = "archive" if archived else "unarchive"
    key = f"{kind}:{item_id}:{client_key}"
    prior = store.action(key)
    if prior is not None and prior["status"] == "done":
        return {"status": "already_done", "kind": kind}
    if store.is_hidden(item_id) == archived:
        return {"status": "already_done", "kind": kind}
    try:
        action_id = store.begin_action(key, item_id, kind, {})
    except sqlite3.IntegrityError:
        if prior is None:   # a concurrent request inserted it between our read and write
            raise ActionError("this action is already in progress") from None
        action_id = prior["id"]   # a failed attempt being retried: reuse its row
    try:
        if gmail is not None:
            _check_account(gmail, item.account)
            if archived:
                gmail.modify_thread(_native_id(item_id), remove=["INBOX"])
            else:
                gmail.modify_thread(_native_id(item_id), add=["INBOX"])
    except (GmailError, ActionError) as e:
        store.finish_action(action_id, "failed")
        raise ActionError(str(e)) from e
    if archived:
        store.hide(item_id, "archived")
    else:
        store.unhide(item_id)
    store.finish_action(action_id, "done")
    return {"status": "done", "kind": kind}


MAX_DRAFT_CHARS = 20_000
_PLACEHOLDER = re.compile(r"\[[^\]\n]{1,80}\]")


def save_draft(store: Store, item_id: str, body: str, seen_updated_at: str,
               gmail: GmailClient | None, client_key: str) -> dict:
    """A threaded Gmail draft from exactly the text in the box. Drafts only: nothing here sends."""
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
        raise ActionError("a new message arrived in this thread; reload before saving")
    key = f"draft:{item_id}:{client_key}"
    prior = store.action(key)
    if prior is not None:
        if prior["status"] == "done":
            return json.loads(prior["payload"])
        if prior["status"] == "unknown":
            raise ActionError("an earlier save may have gone through; check Gmail Drafts")
    sha = hashlib.sha256(body.encode()).hexdigest()
    try:
        action_id = store.begin_action(key, item_id, "draft", {"body_sha256": sha})
    except sqlite3.IntegrityError:
        if prior is None:
            raise ActionError("this save is already in progress") from None
        action_id = prior["id"]
    if gmail is None:
        result = {"status": "done", "kind": "draft", "demo": True,
                  "note": "Demo mode: nothing was saved to Gmail."}
        store.finish_action(action_id, "done", result)
        return result
    try:
        _check_account(gmail, item.account)
        d = drafting.draft_reply(gmail, _native_id(item_id), body)
    except (GmailError, ActionError, drafting.DraftError) as e:
        store.finish_action(action_id, "failed")
        raise ActionError(str(e)) from e
    except requests.RequestException as e:
        # The create call is not retried: it may have reached Gmail. Record that we don't know.
        store.finish_action(action_id, "unknown")
        raise ActionError("Gmail did not answer; check Drafts before trying again") from e
    result = {"status": "done", "kind": "draft", "draft_id": d.draft_id, "url": d.url,
              "body_sha256": sha}
    store.finish_action(action_id, "done", result)
    return result


def relabel(store: Store, item_id: str, bucket: str) -> dict:
    """The owner moves a thread to another bucket. Local only (no Gmail call); the correction is
    kept as a private label and wins over the model until a new message arrives."""
    from .items import BUCKETS
    if bucket not in BUCKETS:
        raise ActionError(f"unknown bucket {bucket!r}")
    item = store.get_item(item_id)
    if item is None:
        raise ActionError("unknown thread (it may have been synced away)")
    store.set_label(item, bucket)
    return {"status": "done", "kind": "relabel", "bucket": bucket}


def set_done(store: Store, item_id: str, done: bool) -> dict:
    """Done: handled, so hide it in FrontDesk only (nothing changes in Gmail or Slack). It
    comes back by itself when a new message arrives. Undo shows it again."""
    item = store.get_item(item_id)
    if item is None:
        raise ActionError("unknown thread (it may have been synced away)")
    if done:
        store.hide(item_id, "done", item.updated_at)
    else:
        store.unhide(item_id)
    return {"status": "done", "kind": "done" if done else "undone"}


def mark_read(store: Store, item_id: str, gmail: GmailClient | None, slack=None) -> dict:
    """Mark a thread read where it lives, once the owner has opened it in FrontDesk.
    Gmail: remove UNREAD from the thread. Slack DMs and group DMs: move the read position to
    the newest message. Slack channel threads: skipped, because Slack can only mark a whole
    channel read, which would hide other unread messages there."""
    item = store.get_item(item_id)
    if item is None:
        raise ActionError("unknown thread (it may have been synced away)")
    if "UNREAD" not in item.labels:
        return {"status": "already_read"}
    if item.source == "slack":
        _, channel, ts = item_id.split(":", 2)
        if ts != "dm":
            return {"status": "skipped", "why": "channel thread"}
        if slack is not None:
            # A DM's deep link points at its newest message: .../archives/<ch>/p<ts digits>.
            m = re.search(r"/p(\d{10})(\d{6})", item.url)
            if not m:
                raise ActionError("can't find the newest message to mark read")
            newest = f"{m.group(1)}.{m.group(2)}"
            try:
                slack.mark(channel, newest)
            except Exception as e:  # noqa: BLE001 - surfaced to the owner as a short error
                raise ActionError(f"Slack would not mark it read ({e})") from e
    elif gmail is not None:
        _check_account(gmail, item.account)
        try:
            gmail.modify_thread(_native_id(item_id), remove=["UNREAD"])
        except GmailError as e:
            raise ActionError(str(e)) from e
    store.set_labels(item_id, [lb for lb in item.labels if lb != "UNREAD"])
    return {"status": "done"}


# ---- owner-side memory: notes and "What's going on". Local only. Every write names its author
# ('owner' from the page, 'session:<name>' from the CLI); there is no default. A record for
# honest writers, not a security boundary (see store.check_author).
def _memory(fn, *args) -> dict:
    from .store import InvalidMemory
    try:
        fn(*args)
    except InvalidMemory as e:
        raise ActionError(str(e)) from e
    return {"status": "done"}


def _author(author) -> str:
    from .store import InvalidMemory, check_author
    try:
        return check_author(author)
    except InvalidMemory as e:
        raise ActionError(str(e)) from e


def _confirmer(author) -> None:
    from .store import OWNER
    if _author(author) != OWNER:
        raise ActionError("only the owner can confirm")


def _situation_id(value) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ActionError("expected a situation item id")
    return value


def save_note(store: Store, who, text, author, append: bool = False) -> dict:
    if not isinstance(who, str) or not isinstance(text, str):
        raise ActionError("expected {who, text, author}")
    return _memory(store.save_note, who, text, author, bool(append))


def confirm_note(store: Store, who, author) -> dict:
    _confirmer(author)
    if not isinstance(who, str):
        raise ActionError("expected {who, author}")
    return _memory(store.confirm_note, who)


def situation_add(store: Store, text, author) -> dict:
    return _memory(store.add_situation, text, author)


def situation_update(store: Store, item_id, text, author) -> dict:
    return _memory(store.update_situation, _situation_id(item_id), text, author)


def situation_confirm(store: Store, item_id, author) -> dict:
    _confirmer(author)
    return _memory(store.confirm_situation, _situation_id(item_id))


def situation_delete(store: Store, item_id, author) -> dict:
    _author(author)
    return _memory(store.delete_situation, _situation_id(item_id))
