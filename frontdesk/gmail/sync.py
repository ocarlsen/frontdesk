"""Pull recent Gmail threads into the store. Upsert by thread id makes a re-run idempotent: a
thread that moved is rewritten (and so re-triaged), one that did not is rewritten unchanged."""
from __future__ import annotations

from dataclasses import dataclass

from ..store import Store
from . import auth
from .client import GmailClient
from .normalize import thread_to_item

IMAGE_MAX = 1_500_000      # bytes of base64 per inline image
IMAGES_PER_MESSAGE = 3_000_000


@dataclass
class SyncResult:
    synced: int
    removed: int


def fetch_inline_images(client: GmailClient, thread: dict) -> None:
    """Gmail leaves attachment bytes out of format=full; fetch the small inline images an HTML
    body references by cid: (signature logos, embedded screenshots) into the payload so
    normalize can embed them. Remote http(s) images are never fetched: those are the tracking
    risk. A failed fetch just leaves the image broken."""
    for msg in thread.get("messages", []):
        budget = IMAGES_PER_MESSAGE
        stack = [msg.get("payload", {})]
        while stack:
            part = stack.pop()
            stack.extend(part.get("parts", []) or [])
            body = part.get("body", {})
            has_cid = any(h.get("name", "").lower() == "content-id"
                          for h in part.get("headers", []))
            if not (has_cid and body.get("attachmentId")
                    and part.get("mimeType", "").lower().startswith("image/")):
                continue
            if body.get("size", 0) * 4 // 3 > min(IMAGE_MAX, budget):
                continue
            try:
                body["data"] = client.get_attachment(msg["id"], body["attachmentId"])
                budget -= len(body["data"])
            except Exception:  # noqa: BLE001 - an image is optional
                pass


def sync(store: Store, settings: dict, log=print, interactive: bool = True) -> SyncResult:
    """One bad thread (a fetch error, an odd MIME tree) is logged and skipped so it cannot
    abort the run; auth and listing failures still raise, since nothing works without them.

    Afterwards, threads the query no longer lists (archived, aged out) are pruned. The keep set
    is every LISTED id, fetched or not, so a thread that merely failed to fetch is kept; and
    pruning only runs after the listing completed, so a failed listing never empties the store."""
    client = GmailClient(auth.credentials(interactive=interactive))
    account = client.profile_email()
    count = 0
    thread_ids = list(client.list_thread_ids(settings["gmail_query"],
                                             int(settings["gmail_max_threads"])))
    for thread_id in thread_ids:
        try:
            thread = client.get_thread(thread_id)
            fetch_inline_images(client, thread)
            item = thread_to_item(thread, account)
        except Exception as e:  # noqa: BLE001 - isolate per thread, report the type only
            log(f"  skipped thread {thread_id}: {type(e).__name__}")
            continue
        if item is None:
            continue
        store.upsert_item(item)
        count += 1
    removed = store.prune("gmail", account, {f"gmail:{t}" for t in thread_ids})
    if removed:
        log(f"  removed {removed} thread(s) no longer in '{settings['gmail_query']}'")
    return SyncResult(count, removed)
