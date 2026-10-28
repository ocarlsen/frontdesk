"""Actions on mail. Every action follows one shape:

1. resolve the item from the store (never from client-supplied fields);
2. write a PENDING row keyed by the client's per-click idempotency key first, so a double-click,
   a retry or a crash cannot repeat the side effect unnoticed; a request whose effect already
   holds (archiving a thread that is already archived) is a no-op;
3. call Gmail with the separate actions token (`frontdesk authorize-actions`), after checking it
   belongs to the same account as the item;
4. record done or failed.

Archive removes the INBOX label: reversible, and Undo adds it back. In demo mode (gmail=None) the
store side runs and Gmail is skipped, so the flow is visible without an account."""
from __future__ import annotations

import re
import sqlite3

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
