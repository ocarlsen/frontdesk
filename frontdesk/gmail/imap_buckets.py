"""`frontdesk inbox-buckets`: every Gmail thread with an INBOX message new since a given time,
sorted into exactly one bucket, read over IMAP. Meant to be called once a day (e.g. by the
personal brief) with --since set to the START time of its own previous run (re-seeing a message
near the boundary is benign; using the end time can silently drop one), so "new since yesterday"
never depends on Gmail's own unread state.

Shares its IMAP mechanics with `frontdesk unanswered` (frontdesk/gmail/imap_unanswered.py,
imported here as `iu`): the same read-only EXAMINE/BODY.PEEK fetch, the same chunked,
fixed-round-trip search+fetch shape, the same 60 s overall cap, and the same one-line
"<step>: <detail>" failure contract (this module's BucketsError is the same shape as
UnansweredError; both are frontdesk.gmail.imap_unanswered._StepError). No model call, nothing
stored, no STORE/COPY/MOVE/EXPUNGE.

Candidates: every thread with at least one INBOX message whose INTERNALDATE is at or after
--since. The X-GM-RAW search can only filter coarsely by day (`newer_than:{n}d`, the same style
imap_unanswered already uses, with `n` padded by a day past --since), so the exact cutoff is then
enforced in code against each message's real INTERNALDATE. Unlike `unanswered`, no `-category:`
exclusion narrows the search: promotions and updates must land in a bucket, not vanish, and there
is no `is:unread` filter either, since a thread "new since yesterday" may already be read.

A live run once misfiled UPS/Amazon order mail as "unanswered" (no List-* headers, no `noreply`-
style local part). Gmail's own category classification catches what header sniffing misses: four
extra X-GM-RAW searches (`category:promotions/updates/social/forums`, same window) collect the
UIDs of messages Gmail itself has sorted out of the primary inbox view. A thread whose newest
inbound message is one of those can never be "unanswered": it goes to `newsletters` if it also
carries the list signals (or its sender matches `newsletter_senders`), else `other`. Mail Gmail
leaves in the primary category is unaffected. The new `person_senders` setting (same matching
rules as the other two sender lists) overrides all of this -- the category rule, the newsletter
header rule, and `is_automated` -- for e.g. a recruiter who mails through Greenhouse/Lever or a
person posting through a Google Group, who should always land in `unanswered`.

Each candidate thread lands in exactly one of three buckets, or is left out as "replied" (the
owner's own message is the newest). Precedence when more than one rule could apply: replied-out
first (not really a candidate for anything else), then a person_senders pin, then an
other_senders pin (notices that look like newsletters), then newsletter
signals (including the category rule once nothing pins or newsletter-flags it), then the ordinary
is_automated/ignore-list check, then other. A newsletter is never "unanswered".

The total/replied/bucket counts are not just arithmetic: `_classify` independently computes
`expected`, the set of thread ids with an in-window candidate message, straight from the parsed
IMAP data, *before* running the bucketing loop. `report()` then re-derives the same set from
`replied` plus every bucket's items and asserts the two match exactly, with every bucket (and
`replied`) pairwise disjoint -- so a thread a future change drops or double-counts fails loudly
(exit 2, step "count") instead of silently passing a tautological check.
"""
from __future__ import annotations

import imaplib
import math
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from email.utils import parseaddr

from . import imap_unanswered as iu

TIMEOUT_S = iu.TIMEOUT_S
DEFAULT_LIMIT = 15
BUCKET_NAMES = ("unanswered", "newsletters", "other")
CATEGORIES = ("promotions", "updates", "social", "forums")

CANDIDATE_QUERY = "in:inbox newer_than:{days}d -in:chats -in:drafts"
OWNER_QUERY = "from:me newer_than:{days}d -in:chats -in:drafts"
CATEGORY_QUERY = "category:{cat} newer_than:{days}d -in:chats -in:drafts"


class BucketsError(iu._StepError):
    pass


def _newsletter_senders(settings: dict) -> tuple[str, ...]:
    return iu._validate_address_list(settings.get("newsletter_senders", []),
                                     "newsletter_senders", BucketsError)


def _other_senders(settings: dict) -> tuple[str, ...]:
    return iu._validate_address_list(settings.get("other_senders", []),
                                     "other_senders", BucketsError)


def _person_senders(settings: dict) -> tuple[str, ...]:
    return iu._validate_address_list(settings.get("person_senders", []),
                                     "person_senders", BucketsError)


def parse_since(value: str) -> datetime:
    """--since must be an ISO 8601 timestamp carrying a UTC offset; a naive or malformed value
    is a loud args failure, never silently treated as UTC or local time."""
    try:
        d = datetime.fromisoformat(value)
    except ValueError as e:
        raise BucketsError("args", f"--since is not a valid ISO 8601 timestamp: {value!r}") from e
    if d.tzinfo is None or d.utcoffset() is None:
        raise BucketsError("args", f"--since must include a UTC offset, e.g. "
                                   f"2026-10-29T00:00:00-07:00 (got {value!r})")
    return d


def _newer_than_days(now: datetime, since: datetime) -> int:
    """Gmail's newer_than: is day-granular; round up to cover --since and pad by one more day,
    then let the exact INTERNALDATE check in _in_window decide what actually counts."""
    return max(1, math.ceil((now - since) / timedelta(days=1)) + 1)


def find_buckets(cfg: iu.ImapConfig, since: datetime, newsletter_senders: tuple[str, ...] = (),
                 person_senders: tuple[str, ...] = (), now: datetime | None = None,
                 other_senders: tuple[str, ...] = (),
                 connect: Callable | None = None,
                 timeout: float = TIMEOUT_S) -> tuple[set[str], set[str], dict[str, list[dict]]]:
    """Returns (expected, replied, buckets): `expected` is every candidate thread id, `replied`
    the ids the owner answered last, `buckets` maps each BUCKET_NAMES entry to its uncapped,
    oldest-first item list. `connect(host, port, timeout)` returns an imaplib.IMAP4-like client;
    tests pass a stub, exactly as imap_unanswered.find_unanswered does."""
    connect = connect or (lambda h, p, t: imaplib.IMAP4_SSL(h, p, timeout=t))
    owner = cfg.account.strip().lower()
    try:
        with iu._overall_timeout(timeout):
            with iu._step("imap connect", error_cls=BucketsError):
                client = connect(cfg.host, iu.PORT, timeout)
            try:
                return _run(client, cfg, owner, since, now or datetime.now(UTC),
                           newsletter_senders, person_senders, cfg.ignore, other_senders)
            finally:
                with suppress(Exception):   # the result (or the real error) stands
                    client.logout()
    except iu._Timeout as e:      # fired between steps
        raise BucketsError("timeout", str(e)) from e


def _empty_result() -> tuple[set[str], set[str], dict[str, list[dict]]]:
    return set(), set(), {name: [] for name in BUCKET_NAMES}


def _run(client, cfg: iu.ImapConfig, owner: str, since: datetime, now: datetime,
        newsletter_senders: tuple[str, ...], person_senders: tuple[str, ...],
        ignore: tuple[str, ...],
        other_senders: tuple[str, ...] = ()) -> tuple[set[str], set[str], dict[str, list[dict]]]:
    with iu._step("imap login", error_cls=BucketsError):
        client.login(cfg.account, cfg.password)
    with iu._step("imap list", error_cls=BucketsError):
        all_mail = iu._all_mail_name(iu._ok(*client.list(), "LIST"))
    with iu._step("imap examine", error_cls=BucketsError):
        iu._ok(*client.select(iu._quote(all_mail), readonly=True), f"EXAMINE {all_mail}")
    days = _newer_than_days(now, since)
    with iu._step("imap search", error_cls=BucketsError):
        cand = iu._search(client, CANDIDATE_QUERY.format(days=days))
    if not cand:
        return _empty_result()
    with iu._step("imap fetch", error_cls=BucketsError):
        cand_dat = iu._fetch(client, cand, iu.FETCH_ITEMS)
    with iu._step("imap search", error_cls=BucketsError):
        mine = iu._search(client, OWNER_QUERY.format(days=days))
    with iu._step("imap fetch", error_cls=BucketsError):
        mine_dat = iu._fetch(client, mine, iu.OWNER_FETCH_ITEMS) if mine else []
    with iu._step("imap search", error_cls=BucketsError):
        category_uids: set[int] = set()
        for cat in CATEGORIES:
            hits = iu._search(client, CATEGORY_QUERY.format(cat=cat, days=days))
            category_uids.update(int(u) for u in hits)
    with iu._step("parse", error_cls=BucketsError):
        cand_msgs, mine_msgs = iu._parse_fetch(cand_dat), iu._parse_fetch(mine_dat)
    with iu._step("classify", error_cls=BucketsError):
        return _classify(cand_msgs, mine_msgs, cfg.account, owner, since, now, ignore,
                         newsletter_senders, person_senders, category_uids, other_senders)


def _in_window(m: iu._Msg, since: datetime) -> bool:
    return not iu._is_draft(m) and m.at >= since


def _bucket_for(headers, addr: str, newsletter_senders: tuple[str, ...],
                ignore: tuple[str, ...], person_senders: tuple[str, ...],
                in_category: bool, other_senders: tuple[str, ...] = ()) -> str:
    if addr and iu.ignored(addr, person_senders):
        return "unanswered"          # pinned: overrides the newsletter and category rules below
    if addr and iu.ignored(addr, other_senders):
        # Pinned to other: notices that carry newsletter headers anyway (Google's account-security
        # mail has List-Id and List-Unsubscribe and sits in Updates, exactly like a newsletter).
        return "other"
    has_newsletter_signal = (
        headers.get("List-Unsubscribe") is not None
        or headers.get("List-Id") is not None
        or (headers.get("Precedence") or "").strip().lower() in ("bulk", "list")
        or (bool(addr) and iu.ignored(addr, newsletter_senders))
    )
    if has_newsletter_signal:
        return "newsletters"
    if in_category:                  # Gmail sorted it out of primary; not list-flagged either
        return "other"
    if addr and not iu.is_automated(headers, addr) and not iu.ignored(addr, ignore):
        return "unanswered"
    return "other"


def _item(account: str, thrid: int, name: str, addr: str, last: iu._Msg, now: datetime,
         n_messages: int) -> dict:
    return {
        "thread_id": str(thrid),
        "gmail_url": iu.gmail_url(account, thrid),
        "from_name": name.strip(),
        "from_addr": addr,
        "subject": iu.decode_rfc2047(last.headers.get("Subject")),
        "last_at": last.at.isoformat(),
        "age_days": max(0, (now - last.at) // timedelta(days=1)),
        "n_messages": n_messages,
    }


def _classify(cand: list[iu._Msg], mine: list[iu._Msg], account: str, owner: str,
              since: datetime, now: datetime, ignore: tuple[str, ...],
              newsletter_senders: tuple[str, ...], person_senders: tuple[str, ...],
              category_uids: set[int], other_senders: tuple[str, ...] = (),
              ) -> tuple[set[str], set[str], dict[str, list[dict]]]:
    """Threads come from the candidates only (an INBOX message at or after --since); the owner's
    own messages only decide whether the owner spoke last, exactly as imap_unanswered._classify
    does. `expected` is computed here, straight from the in-window candidates, independently of
    the bucketing loop below, so report()'s invariant check is not tautological."""
    cand = [m for m in cand if _in_window(m, since)]
    mine = [m for m in mine if _in_window(m, since)]
    expected = {str(m.thrid) for m in cand}

    threads: dict[int, dict[int, iu._Msg]] = {}
    for m in cand:
        threads.setdefault(m.thrid, {})[m.uid] = m
    owner_uids = {m.uid for m in mine}
    for m in mine:
        if m.thrid in threads:
            threads[m.thrid].setdefault(m.uid, m)

    replied_ids: set[str] = set()
    buckets: dict[str, list[dict]] = {name: [] for name in BUCKET_NAMES}
    for thrid, by_uid in threads.items():
        ms = list(by_uid.values())
        last = max(ms, key=lambda m: (m.at, m.uid))
        name, addr = parseaddr(iu.decode_rfc2047(last.headers.get("From")))
        addr = addr.strip().lower()
        if last.uid in owner_uids or (addr and addr == owner):
            replied_ids.add(str(thrid))
            continue
        bucket = _bucket_for(last.headers, addr, newsletter_senders, ignore, person_senders,
                             last.uid in category_uids, other_senders)
        item = _item(account, thrid, name, addr, last, now, len(ms))
        if bucket == "newsletters":
            item["read_url"] = item["gmail_url"]
        buckets[bucket].append(item)
    for items in buckets.values():
        items.sort(key=lambda it: (datetime.fromisoformat(it["last_at"]), it["thread_id"]))
    return expected, replied_ids, buckets


def report(classified: tuple[set[str], set[str], dict[str, list[dict]]], limit: int,
          since_str: str) -> dict:
    """The JSON contract. `expected` (every candidate thread, computed independently in
    _classify) must equal the union of `replied` and every bucket's thread ids, with all of those
    sets pairwise disjoint; otherwise this is a real inconsistency -- a thread dropped or
    double-counted -- and fails loudly, step 'count', exit 2."""
    if limit < 0:
        raise BucketsError("args", "--limit must be 0 or more")
    expected, replied_ids, buckets = classified
    named: dict[str, set[str]] = {"replied": set(replied_ids)}
    for bname in BUCKET_NAMES:
        named[bname] = {it["thread_id"] for it in buckets[bname]}
    names = list(named)
    overlaps = [(names[i], names[j], sorted(named[names[i]] & named[names[j]]))
               for i in range(len(names)) for j in range(i + 1, len(names))
               if named[names[i]] & named[names[j]]]
    union = set().union(*named.values()) if named else set()
    if union != expected or overlaps:
        missing, extra = sorted(expected - union), sorted(union - expected)
        raise BucketsError("count", f"expected {len(expected)} thread(s); got "
                                    f"{ {k: len(v) for k, v in named.items()} }; "
                                    f"missing {missing}, extra {extra}, overlaps {overlaps}")
    out_buckets = {name: {"total": len(buckets[name]), "items": buckets[name][:limit]}
                  for name in BUCKET_NAMES}
    return {"since": since_str, "total": len(expected), "replied": len(replied_ids),
           "buckets": out_buckets}
