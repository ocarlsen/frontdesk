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


STARRED_MAX = 200


def starred_archived(client: GmailClient, store: Store) -> set[str]:
    """Threads FrontDesk archived that are still starred in Gmail. Kept as stored (not refetched):
    a new message brings the thread back to the inbox, and the main listing fetches it then. If
    the starred listing fails, every archived thread is kept for this round."""
    archived = store.archived_ids("gmail")
    if not archived:
        return set()
    try:
        starred = {f"gmail:{t}" for t in client.list_thread_ids("is:starred", STARRED_MAX)}
    except Exception:  # noqa: BLE001 - never prune on a failed listing
        return archived
    return archived & starred


def sync(store: Store, settings: dict, log=print, interactive: bool = True) -> SyncResult:
    """One bad thread (a fetch error, an odd MIME tree) is logged and skipped so it cannot
    abort the run; auth and listing failures still raise, since nothing works without them.

    Afterwards, threads the query no longer lists (archived, aged out) are pruned. The keep set
    is every LISTED id, fetched or not, so a thread that merely failed to fetch is kept; and
    pruning only runs after the listing completed, so a failed listing never empties the store.

    A thread FrontDesk archived that Gmail still has starred is kept (hidden from the list, shown
    in the Starred view) until it is unstarred; one that is back in the inbox shows again."""
    client = GmailClient(auth.credentials(interactive=interactive))
    account = client.profile_email()
    count = 0
    thread_ids = list(client.list_thread_ids(settings["gmail_query"],
                                             int(settings["gmail_max_threads"])))
    # Threads the owner kept from a search sit outside the query: fetch them too, so new replies
    # show, and keep them through prune until they are archived or marked done.
    kept = sorted(i.partition(":")[2] for i in store.kept_ids("gmail"))
    # Gmail's thread listing can be stale: it has listed years-old threads for in:inbox whose
    # messages no longer carry INBOX (Gmail's own inbox does not show them). The fetched
    # messages' labels are the truth, so an inbox query drops a listed thread without INBOX.
    inbox_only = "in:inbox" in settings["gmail_query"].lower().split()
    stale: set[str] = set()
    for thread_id in thread_ids + [k for k in kept if k not in set(thread_ids)]:
        try:
            thread = client.get_thread(thread_id)
            fetch_inline_images(client, thread)
            item = thread_to_item(thread, account)
        except Exception as e:  # noqa: BLE001 - isolate per thread, report the type only
            log(f"  skipped thread {thread_id}: {type(e).__name__}")
            continue
        if item is None:
            continue
        if inbox_only and "INBOX" not in item.labels and thread_id not in kept:
            stale.add(thread_id)
            continue
        store.upsert_item(item)
        if "INBOX" in item.labels and store.hidden_reason(item.id) == "archived":
            store.unhide(item.id)          # moved back to the inbox since FrontDesk archived it
        count += 1
    keep = ({f"gmail:{t}" for t in thread_ids if t not in stale} | {f"gmail:{k}" for k in kept}
            | starred_archived(client, store))
    if stale:
        log(f"  left out {len(stale)} thread(s) Gmail listed for the inbox without the INBOX label")
    removed = store.prune("gmail", account, keep)
    if removed:
        log(f"  removed {removed} thread(s) no longer in '{settings['gmail_query']}'")
    return SyncResult(count, removed)
