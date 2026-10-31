"""Local web UI. Stdlib only: a page, its JS and CSS, a JSON list over Store.ranked(), one
message-HTML route, and two POST routes: /api/sync READS Gmail (read-only token) and ranks new
threads; /api/action archives or un-archives one thread through frontdesk.actions, using the
separate actions token the owner granted with `frontdesk authorize-actions`.

Access control, in order, on every request:
1. Host allowlist (DNS-rebinding defence): the Host header must be localhost, an IP literal, or a
   name listed in settings. A rebinding attack arrives under the attacker's hostname, so it is
   refused before any data is read.
2. Token, only when bound beyond loopback: a random token stored 0600 in FRONTDESK_HOME. Opening
   /index.html?token=... once sets an HttpOnly, SameSite=Strict cookie; every route then requires
   it. On 127.0.0.1 the OS already limits callers to this machine.
3. POST additionally requires a custom header and a same-host Origin (CSRF).

Email content is untrusted. The list is sent as JSON and rendered with textContent only. A
message's HTML is served from /msg under its own CSP (no script, no remote load, no forms) with
<meta http-equiv> removed (CSP does not govern a meta refresh), and the page frames it in a
sandboxed iframe without allow-scripts."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
from dataclasses import asdict
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from .. import config
from ..items import GMAIL_THREAD, Item
from ..store import Store

STATIC_DIR = Path(__file__).parent
STATIC = {
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; "
       "frame-ancestors 'none'")
# For one email's HTML: inline styles and data: images only. No script, no remote image
# (tracking pixels), no fonts, no forms; framable only by our own page.
MSG_CSP = ("default-src 'none'; style-src 'unsafe-inline'; img-src data:; script-src 'none'; "
           "form-action 'none'; base-uri 'none'; frame-ancestors 'self'")
MSG_HEAD = ('<!doctype html><meta charset="utf-8"><base target="_blank">'
            '<style>html,body{margin:0;background:#fff;color:#202124;'
            'font:14px/1.5 Arial,Helvetica,sans-serif;overflow-wrap:anywhere}'
            'img{max-width:100%;height:auto}table{max-width:100%}</style>')
_META_EQUIV = re.compile(r"<meta\b[^>]*http-equiv[^>]*>", re.I)
COOKIE = "fd_token"
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
TEXT = "text/plain; charset=utf-8"


def ranked_payload(store: Store, signoff: str = "") -> list[dict]:
    """HTML bodies stay out of the list payload (fetched per message from /msg); each
    message carries has_html instead. A proposed email reply gets the owner's sign-off.
    Each item carries `starred`, and `hidden` ('archived' or 'done', else ''): a hidden item is
    listed only when starred, for the Starred view, after every visible one."""
    from ..assist import with_signoff
    with_html = store.html_indexes()
    unread_here = store.local_unread_ids()
    out = []
    rows = [(i, t, "") for i, t in store.ranked()]
    rows += [(i, t, store.hidden_reason(i.id)) for i, t in store.ranked(hidden=True)
             if store.is_starred(i)]
    for item, tri, hidden in rows:
        d = item.to_dict()
        d["starred"] = store.is_starred(item)
        if item.id in unread_here and "UNREAD" not in d["labels"]:
            d["labels"] = [*d["labels"], "UNREAD"]
        d["kept"] = store.is_kept(item.id)
        d["hidden"] = hidden
        for i, m in enumerate(d["messages"]):
            m.pop("html", None)
            if not m.get("sender_key"):   # Gmail has none; its key is the address in sender
                m.pop("sender_key", None)
            m["has_html"] = i in with_html.get(item.id, set())
        t = asdict(tri) if tri else None
        if t and item.source == "gmail":
            t["proposed_reply"] = with_signoff(t["proposed_reply"], signoff)
        out.append({"item": d, "triage": t})
    return out


def signed_history(history: list[dict], source: str) -> list[dict]:
    """Ask drafts saved before the sign-off existed (or before it changed) get the current one,
    so "Use as reply" always carries it. Email only."""
    from ..assist import with_signoff
    if source != "gmail":
        return history
    sign = config.settings()["reply_signoff"]
    return [{**h, "draft_reply": with_signoff(h["draft_reply"], sign)} if h.get("draft_reply")
            else h for h in history]


def ask_payload(store: Store, item: Item) -> dict:
    """The Ask panel's data: the built-in question the Ask box starts with (`advise`) and
    history, plus the thread's people (people_payload), which the People strip shows too."""
    from ..assist import ADVISE
    return {"advise": ADVISE,
            "history": signed_history(store.ask_history(item.id), item.source),
            **people_payload(store, item)}


def people_payload(store: Store, item: Item) -> dict:
    """One notes box per PERSON in the thread (`people` lists one address per person, `notes`
    is keyed by it, `aliases` holds their other addresses and `names` the name the owner typed,
    `display` how to show a key that is not readable: a Slack user's display name, from the
    thread first). The owner is never among them. The static demo exports this per thread."""
    from ..assist import others
    oth = others(item)
    rep: dict[str, str] = {}
    aliases: dict[str, list[str]] = {}
    names: dict[str, str] = {}
    for p in store.people_for(oth):
        first = p["matched"][0]
        for k in p["matched"]:
            rep[k] = first
        aliases[first] = [a for a in p["addresses"] if a != first]
        if p["name"]:
            names[first] = p["name"]
    people = [a for a in oth if rep.get(a.lower(), a.lower()) == a.lower()]
    shown = {**store.slack_names(), **{k.lower(): v for k, v in item.names.items()}}
    display = {a: label for a in [*people, *(x for v in aliases.values() for x in v)]
               if (label := address_label(a, shown))}
    return {"notes": store.notes_for(people), "people": people, "aliases": aliases,
            "names": names, "display": display}


def address_label(addr: str, slack_names: dict[str, str]) -> str:
    """How the page shows an address that is not readable as is ('' for one that is, like an
    email address): a Slack user key as their display name, a bot key likewise, an old Slack
    display-name alias as itself. Display names are the other party's text: page only."""
    from ..store import is_legacy_slack_name, is_slack_key
    if is_slack_key(addr):
        return slack_names.get(addr) or ("Slack bot" if ":bot:" in addr else "Slack user")
    if is_legacy_slack_name(addr):
        return addr
    return ""


def message_html(store: Store, item_id: str, index: int) -> str | None:
    html = store.message_html(item_id, index)
    return MSG_HEAD + _META_EQUIV.sub("", html) if html else None


_sync_lock = threading.Lock()
# The latest sync, manual or automatic, for the page's "synced at" line. One server, one process.
_last_sync: dict = {"at": "", "ok": None, "summary": "", "auto_sync_minutes": 0}


def _record_sync(ok: bool, summary: str) -> None:
    from ..store import now
    _last_sync.update(at=now(), ok=ok, summary=summary)


def run_sync(db_path: Path, settings: dict) -> tuple[int, dict]:
    """Sync then triage, for the page's Sync button. Never opens a consent flow (a server request
    can't), and a busy lock answers 409 instead of queueing a second Gmail pull."""
    from .. import triage
    from ..gmail.auth import AuthError
    from ..gmail.client import GmailError
    from ..providers import ProviderError, get_provider
    from ..sources import sync_all
    if settings.get("demo"):
        return HTTPStatus.CONFLICT, {"error": "Sync is off in demo mode (synthetic inbox)."}
    if not _sync_lock.acquire(blocking=False):
        return HTTPStatus.CONFLICT, {"error": "A sync is already running."}
    store = Store(db_path)
    try:
        try:
            res = sync_all(store, settings, log=lambda *_: None, interactive=False)
        except (AuthError, GmailError) as e:
            _record_sync(False, str(e))
            return HTTPStatus.BAD_GATEWAY, {"error": str(e)}
        out = {"synced": sum(r.synced for r in res.values()),
               "removed": sum(r.removed for r in res.values()), "triaged": 0, "failed": 0,
               "sources": sorted(res)}
        try:
            done: list = []
            out["triaged"], out["failed"] = triage.run(store, get_provider(settings),
                                                       log=lambda *_: None, done=done,
                                                       profile=settings.get("owner_profile", ""))
            out["cost_usd"] = triage.summarize(done)["cost_usd"]
        except ProviderError as e:
            out["triage_error"] = str(e)
        _record_sync(True, f"synced {out['synced']}, ranked {out['triaged']}")
        return HTTPStatus.OK, out
    finally:
        store.db.close()
        _sync_lock.release()


def start_autosync(db_path: Path, minutes: int) -> threading.Thread | None:
    """Sync and rank every `minutes` (0: off). Shares run_sync's lock with the Sync button, so
    the two never overlap; a busy lock just skips this round. Settings are re-read each round."""
    if minutes <= 0:
        return None
    _last_sync["auto_sync_minutes"] = minutes

    def loop():
        while True:
            threading.Event().wait(minutes * 60)
            try:
                run_sync(db_path, config.settings())
            except Exception as e:  # noqa: BLE001 - keep the loop alive; report the type only
                _record_sync(False, type(e).__name__)
                print(f"auto-sync: {type(e).__name__}", flush=True)

    t = threading.Thread(target=loop, name="auto-sync", daemon=True)
    t.start()
    return t


# Owner-side memory writes (people's notes, "What's going on"): local only, each names its author.
MEMORY_KINDS = ("note", "note_suggestion", "note_confirm", "person_update", "person_confirm",
                "person_delete", "person_merge", "situation_add", "situation_update",
                "situation_confirm", "situation_delete")


def run_memory(db_path: Path, settings: dict, kind: str, req: dict) -> tuple[int, dict]:
    from .. import actions
    if settings.get("demo"):   # like the profile: the demo's memory is empty and read-only
        what = "What's going on needs" if kind.startswith("situation") else "Memory needs"
        return HTTPStatus.CONFLICT, {"error": f"Demo mode: {what} your own copy."}
    store = Store(db_path)
    try:
        a = req.get("author")
        if kind == "note":
            out = actions.save_note(store, req.get("who"), req.get("text"), a,
                                    bool(req.get("append")))
        elif kind == "note_suggestion":
            out = actions.save_suggested_note(store, req.get("item_id"), req.get("who"),
                                              req.get("text"), a)
        elif kind == "note_confirm":
            out = actions.confirm_note(store, req.get("who"), a)
        elif kind == "person_update":
            out = actions.person_update(store, req.get("id"), req.get("text"), a,
                                        req.get("name"))
        elif kind == "person_confirm":
            out = actions.person_confirm(store, req.get("id"), a)
        elif kind == "person_delete":
            out = actions.person_delete(store, req.get("id"), a)
        elif kind == "person_merge":
            out = actions.person_merge(store, req.get("id"), req.get("into"), a)
        elif kind == "situation_add":
            out = actions.situation_add(store, req.get("text"), a)
        elif kind == "situation_update":
            out = actions.situation_update(store, req.get("id"), req.get("text"), a)
        elif kind == "situation_confirm":
            out = actions.situation_confirm(store, req.get("id"), a)
        else:
            out = actions.situation_delete(store, req.get("id"), a)
        return HTTPStatus.OK, out
    except actions.ActionError as e:
        return HTTPStatus.BAD_REQUEST, {"error": str(e)}
    finally:
        store.db.close()


DEMO_MEMORY = {"demo": True, "profile": "", "signoff": "", "situation": [], "people": [],
               "migration": None}


def memory_payload(store: Store) -> dict:
    """Everything owner-side FrontDesk keeps, for the Memory page (GET /api/memory). Each person
    carries `mail_names`: display names seen in mail for their addresses, which the page shows
    greyed as unconfirmed; they are sender-controlled and never reach a model."""
    cfg = config.settings()
    names = store.mail_names()
    slack = store.slack_names()
    people = [{**p, "mail_names": sorted({names[a] for a in p["addresses"] if a in names}),
               "address_labels": _address_labels(p["addresses"], slack)}
              for p in store.people_all()]
    mig = store.meta("people_migrated")
    return {"demo": False, "profile": cfg.get("owner_profile", ""),
            "signoff": cfg.get("reply_signoff", ""), "situation": store.situation(),
            "people": people, "migration": json.loads(mig) if mig else None}


def _address_labels(addrs: list[str], slack: dict[str, str]) -> dict[str, dict]:
    """{address: {"text", "kind"}} for the Memory page's address line, for the addresses that
    are not readable as is. kind 'slack' (a user key: "Name (Slack)", the key goes in a title
    attribute), 'slack_name' (an old display-name alias that is linked: the person also has a
    user key) or 'slack_unlinked' (no user key yet: "Slack name, not linked to a user")."""
    from ..store import is_legacy_slack_name, is_slack_key
    linked = any(is_slack_key(a) for a in addrs)
    out = {}
    for a in addrs:
        if is_slack_key(a):
            out[a] = {"text": address_label(a, slack), "kind": "slack"}
        elif is_legacy_slack_name(a):
            out[a] = {"text": a, "kind": "slack_name" if linked else "slack_unlinked"}
    return out


def memory_export(store: Store) -> dict:
    """"Download my memory": the same records as the Memory page, minus the display names
    from mail (those are mail, not memory)."""
    from ..store import now
    m = memory_payload(store)
    return {"exported_at": now(), "format": "frontdesk-memory-1", "profile": m["profile"],
            "signoff": m["signoff"], "situation": m["situation"],
            "people": [{k: p[k] for k in ("id", "name", "addresses", "note", "author",
                                          "created_at", "updated_at")} for p in m["people"]],
            "migration": m["migration"]}


def gmail_draft(db_path: Path, settings: dict, item_id: str,
                client_factory=None) -> tuple[int, dict]:
    """The thread's unsent Gmail draft, read from Gmail on each open (GET /api/gmail-draft).
    FrontDesk keeps no copy, so an edit made in Gmail shows here and a sent or discarded draft
    disappears. Read-only token; never opens a consent flow."""
    import requests

    from .. import drafting
    from ..gmail.auth import AuthError, credentials
    from ..gmail.client import GmailClient, GmailError
    if settings.get("demo") or not item_id.startswith("gmail:"):
        return HTTPStatus.OK, {"draft": None}
    store = Store(db_path)
    try:
        item = store.get_item(item_id)
    finally:
        store.db.close()
    if item is None:
        return HTTPStatus.NOT_FOUND, {"error": "unknown thread"}
    try:
        gmail = (client_factory or (lambda: GmailClient(credentials(interactive=False))))()
        d = drafting.thread_draft(gmail.get_thread(item_id.partition(":")[2]))
    except AuthError as e:
        return HTTPStatus.BAD_GATEWAY, {"error": str(e)}
    except (GmailError, requests.RequestException):
        # Not str(e): a Gmail error can quote the response body.
        return HTTPStatus.BAD_GATEWAY, {"error": "Gmail did not answer"}
    if d is None:
        return HTTPStatus.OK, {"draft": None}
    return HTTPStatus.OK, {"draft": {"body": d["body"],
                                     "url": drafting.draft_url(item.account, d["message_id"])}}


def run_search(settings: dict, query: str, client_factory=None, slack_factory=None,
               db_path: Path | None = None) -> tuple[int, dict]:
    """GET /api/search: all of Gmail (archived too) and, when Slack is connected, all of Slack,
    for `query`, both read-only and at the same time. Nothing is stored and nothing is sent to a
    model. One source failing does not hide the other: its error travels beside the results.
    Never opens a consent flow."""
    from concurrent.futures import ThreadPoolExecutor

    import requests

    from ..gmail.auth import AuthError, credentials
    from ..gmail.client import GmailClient, GmailError
    from ..gmail.search import MAX_QUERY_CHARS, search
    from ..slack.client import SlackClient, SlackError
    from ..slack.search import search as slack_search
    query = query.strip()
    if not query or len(query) > MAX_QUERY_CHARS:
        return HTTPStatus.BAD_REQUEST, {"error": "type a search of up to 500 characters"}
    if settings.get("demo"):
        return HTTPStatus.OK, {"results": [], "demo": True, "slack": None}

    def gmail_part() -> tuple[list, str]:
        try:
            gmail = (client_factory or (lambda: GmailClient(credentials(interactive=False))))()
            return search(gmail, query), ""
        except AuthError as e:
            return [], str(e)
        except (GmailError, requests.RequestException):
            return [], "Gmail did not answer"   # not str(e): it can quote the response body

    def slack_part() -> tuple[list | None, str]:
        factory = slack_factory
        if factory is None:
            if not (os.environ.get("SLACK_USER_TOKEN") or settings.get("slack_keychain_service")):
                return None, ""
            from ..sources import slack_token
            tok = slack_token(settings)
            if not tok:
                return None, ""                   # Slack not connected: no Slack section
            factory = lambda: SlackClient(tok)   # noqa: E731
        try:
            return slack_search(factory(), query), ""
        except SlackError as e:
            if "missing_scope" in str(e):
                return [], "searching Slack needs the search:read permission on your Slack app"
            return [], "Slack did not answer"
        except requests.RequestException:
            return [], "Slack did not answer"

    with ThreadPoolExecutor(max_workers=2) as pool:
        g, sl = pool.submit(gmail_part), pool.submit(slack_part)
        (results, gerr), (slack, serr) = g.result(), sl.result()
    if gerr and slack is None:
        return HTTPStatus.BAD_GATEWAY, {"error": gerr}
    if db_path is not None:
        store = Store(db_path)
        try:
            if not gerr:
                store.log_usage("search", source="gmail")
            if slack is not None and not serr:
                store.log_usage("search", source="slack")
        finally:
            store.db.close()
    return HTTPStatus.OK, {"results": results, "gmail_error": gerr, "slack": slack,
                           "slack_error": serr}


_GMAIL_THREAD = GMAIL_THREAD


def _read_gmail(client_factory):
    from ..gmail.auth import credentials
    from ..gmail.client import GmailClient
    return (client_factory or (lambda: GmailClient(credentials(interactive=False))))()


def search_thread(settings: dict, item_id: str, client_factory=None) -> tuple[int, dict]:
    """GET /api/search/thread: one search result's whole thread, read-only, for reading in place.
    Nothing is stored and no model sees it. Bodies are plain text: HTML display needs a stored
    item (the /msg route serves only those), so a preview never renders sender HTML."""
    import requests

    from ..gmail.auth import AuthError
    from ..gmail.client import GmailError
    from ..gmail.search import fetch_item
    if not _GMAIL_THREAD.fullmatch(item_id or ""):
        return HTTPStatus.BAD_REQUEST, {"error": "not a Gmail thread id"}
    if settings.get("demo"):
        return HTTPStatus.CONFLICT, {"error": "Search is off in demo mode."}
    try:
        item = fetch_item(_read_gmail(client_factory), item_id.partition(":")[2])
    except AuthError as e:
        return HTTPStatus.BAD_GATEWAY, {"error": str(e)}
    except (GmailError, requests.RequestException):
        return HTTPStatus.BAD_GATEWAY, {"error": "Gmail did not answer"}
    if item is None:
        return HTTPStatus.NOT_FOUND, {"error": "that thread holds only drafts"}
    d = item.to_dict()
    for m in d["messages"]:
        m.pop("html", None)
        m["has_html"] = False
    return HTTPStatus.OK, {"item": d}


def keep_result(db_path: Path, settings: dict, item_id: str, client_factory=None,
                provider_factory=None, slack_factory=None) -> tuple[int, dict]:
    """POST /api/action kind=keep: store a search result as a thread FrontDesk keeps (sync then
    keeps it current) and rank it once, so it gets a summary, a reason and a proposed reply like
    any other thread. Ranking is one model call; if it fails the thread is kept, unranked."""
    import requests

    from ..gmail.auth import AuthError
    from ..gmail.client import GmailError
    from ..gmail.search import fetch_item
    if (item_id or "").startswith("slack:"):
        return keep_slack(db_path, settings, item_id, slack_factory, provider_factory)
    if not _GMAIL_THREAD.fullmatch(item_id or ""):
        return HTTPStatus.BAD_REQUEST, {"error": "not a Gmail thread id"}
    if settings.get("demo"):
        return HTTPStatus.CONFLICT, {"error": "Demo mode: nothing can be kept."}
    try:
        item = fetch_item(_read_gmail(client_factory), item_id.partition(":")[2],
                          inline_images=True)
    except AuthError as e:
        return HTTPStatus.BAD_GATEWAY, {"error": str(e)}
    except (GmailError, requests.RequestException):
        return HTTPStatus.BAD_GATEWAY, {"error": "Gmail did not answer"}
    if item is None:
        return HTTPStatus.NOT_FOUND, {"error": "that thread holds only drafts"}
    return _keep_and_rank(db_path, settings, item, "gmail", provider_factory)


def keep_slack(db_path: Path, settings: dict, item_id: str, slack_factory=None,
               provider_factory=None) -> tuple[int, dict]:
    """Keep a Slack search match: fetch its conversation (the DM, or the channel thread) as sync
    would, store it kept, so sync keeps it current until it is marked done, and rank it once."""
    import time

    import requests

    from ..slack.client import SlackClient, SlackError
    from ..slack.sync import SLACK_ITEM, fetch_one, workspace
    if not SLACK_ITEM.fullmatch(item_id or ""):
        return HTTPStatus.BAD_REQUEST, {"error": "not a Slack conversation id"}
    if settings.get("demo"):
        return HTTPStatus.CONFLICT, {"error": "Demo mode: nothing can be kept."}
    try:
        if slack_factory is None:
            from ..sources import slack_token
            tok = slack_token(settings)
            if not tok:
                return HTTPStatus.PRECONDITION_FAILED, {"error": "Slack is not connected"}
            client = SlackClient(tok)
        else:
            client = slack_factory()
        floor = time.time() - float(settings.get("slack_unread_days", 90)) * 86400
        got = fetch_one(client, workspace(client), item_id, floor)
    except (SlackError, requests.RequestException) as e:
        return HTTPStatus.BAD_GATEWAY, {"error": f"Slack did not answer ({type(e).__name__})"}
    if got is None:
        return HTTPStatus.NOT_FOUND, {"error": "nothing left in that conversation"}
    return _keep_and_rank(db_path, settings, got[0], "slack", provider_factory)


def _keep_and_rank(db_path: Path, settings: dict, item, source: str,
                   provider_factory=None) -> tuple[int, dict]:
    from .. import triage
    from ..providers import ProviderError, ProviderRefusal, get_provider
    store = Store(db_path)
    try:
        store.keep(item)
        store.log_usage("keep", source=source)
        profile = settings.get("owner_profile", "")
        version = triage.prompt_version(profile)
        try:
            provider = (provider_factory or (lambda: get_provider(settings)))()
            store.save_triage(triage.triage_item(provider, item, profile=profile))
            ranked = True
        except ProviderRefusal as e:
            store.record_failure(item, version, "refusal", str(e))
            ranked = False
        except ProviderError as e:
            store.record_failure(item, version, "error", str(e))
            ranked = False
    finally:
        store.db.close()
    return HTTPStatus.OK, {"status": "done", "kind": "keep", "ranked": ranked}


def run_action(db_path: Path, settings: dict, req: dict) -> tuple[int, dict]:
    from .. import actions
    from ..gmail.auth import AuthError, action_credentials
    from ..gmail.client import GmailClient
    kind, item_id, key = req.get("kind"), req.get("item_id"), req.get("key")
    if kind in ("send_confirm", "send_cancel"):
        from .. import sending
        aid = req.get("action_id")
        if not isinstance(aid, int):
            return HTTPStatus.BAD_REQUEST, {"error": "expected {kind, action_id}"}
        store = Store(db_path)
        try:
            fn = sending.confirm if kind == "send_confirm" else sending.cancel
            return HTTPStatus.OK, fn(store, aid)
        except actions.ActionError as e:
            return HTTPStatus.CONFLICT, {"error": str(e)}
        finally:
            store.db.close()
    if kind in MEMORY_KINDS:
        return run_memory(db_path, settings, kind, req)
    if kind == "keep":
        return keep_result(db_path, settings, item_id if isinstance(item_id, str) else "")
    if kind == "result":
        # A Gmail search result, not stored: a label change straight in Gmail (actions token).
        op = req.get("op")
        if not isinstance(item_id, str) or not isinstance(op, str):
            return HTTPStatus.BAD_REQUEST, {"error": "expected {kind, item_id, op}"}
        try:
            gmail = None if settings.get("demo") else GmailClient(action_credentials())
        except AuthError as e:
            return HTTPStatus.PRECONDITION_FAILED, {"error": str(e)}
        try:
            return HTTPStatus.OK, actions.result_op(item_id, op, gmail)
        except actions.ActionError as e:
            return HTTPStatus.CONFLICT, {"error": str(e)}
    if kind == "profile":
        item_id = key = ""
    elif kind not in ("archive", "unarchive", "draft", "relabel", "send_prepare", "done",
                      "undone", "read", "unread", "ask", "star", "unstar", "inbox") \
            or not isinstance(item_id, str) or not isinstance(key, str):
        return HTTPStatus.BAD_REQUEST, {"error": "expected {kind, item_id, key}"}
    if kind == "profile":   # the owner's own words for the model; local settings only
        text = req.get("text")
        if settings.get("demo"):
            return HTTPStatus.CONFLICT, {"error": "Demo mode: the profile can't be changed."}
        if not isinstance(text, str) or len(text) > config.PROFILE_MAX:
            return HTTPStatus.BAD_REQUEST, {"error": f"profile must be text, at most "
                                                     f"{config.PROFILE_MAX} characters"}
        sign = req.get("signoff")
        if sign is not None and (not isinstance(sign, str) or len(sign) > config.SIGNOFF_MAX):
            return HTTPStatus.BAD_REQUEST, {"error": f"sign-off must be text, at most "
                                                     f"{config.SIGNOFF_MAX} characters"}
        config.save_setting("owner_profile", text.strip())
        if sign is not None:
            config.save_setting("reply_signoff", sign.strip())
        return HTTPStatus.OK, {"status": "done", "kind": "profile"}
    if kind == "ask":
        if settings.get("demo"):
            return HTTPStatus.CONFLICT, {"error": "Demo mode: Ask needs a live model."}
        from .. import assist
        from ..providers import ProviderError, get_provider
        from ..store import InvalidMemory, check_author
        try:
            author = check_author(req.get("author"))
        except InvalidMemory as e:
            return HTTPStatus.BAD_REQUEST, {"error": str(e)}
        store = Store(db_path)
        try:
            q, mode, draft = req.get("question", ""), req.get("mode", "ask"), req.get("draft", "")
            if mode not in ("ask", "second", "polish") or not isinstance(q, str) \
                    or not isinstance(draft, str) or len(q) > 4000 or len(draft) > 8000:
                return HTTPStatus.BAD_REQUEST, {"error": "expected question/draft text and a mode"}
            s = config.settings()
            choice = req.get("model")
            if mode != "ask":            # the reviewer is a different, stronger model
                s = {**s, "provider": "anthropic", "model": s["review_model"]}
                return HTTPStatus.OK, assist.ask(store, get_provider(s), str(item_id), q,
                                                 s["owner_profile"], author=author,
                                                 signoff=s["reply_signoff"], mode=mode,
                                                 draft=draft)
            available = available_models(s)
            if choice == "all":
                return HTTPStatus.OK, ask_all(db_path, s, available, str(item_id), q, author)
            if isinstance(choice, int) and 0 <= choice < len(available):
                m = available[choice]
                s = {**s, "provider": m["provider"], "model": m["model"]}
                return HTTPStatus.OK, assist.ask(store, get_provider(s), str(item_id), q,
                                                 s["owner_profile"], author=author,
                                                 signoff=s["reply_signoff"],
                                                 label=m["label"])
            return HTTPStatus.OK, assist.ask(store, get_provider(s), str(item_id), q,
                                             s["owner_profile"], author=author,
                                                 signoff=s["reply_signoff"])
        except ProviderError as e:
            return HTTPStatus.BAD_GATEWAY, {"error": str(e)}
        finally:
            store.db.close()
    if kind == "unread":
        if settings.get("demo"):
            return HTTPStatus.OK, {"status": "skipped"}
        store = Store(db_path)
        try:
            item = store.get_item(str(item_id))
            gmail = None
            if item is not None and item.source == "gmail":
                try:
                    gmail = GmailClient(action_credentials())
                except AuthError as e:
                    return HTTPStatus.PRECONDITION_FAILED, {"error": str(e)}
            return HTTPStatus.OK, actions.mark_unread(store, str(item_id), gmail)
        except actions.ActionError as e:
            return HTTPStatus.CONFLICT, {"error": str(e)}
        finally:
            store.db.close()
    if kind == "read":
        # Opening a thread marks it read only when mark_read_on_open is on; Shift+I or the Mark
        # read button ("explicit") always does.
        if settings.get("demo") or not (req.get("explicit") is True
                                        or config.settings()["mark_read_on_open"]):
            return HTTPStatus.OK, {"status": "skipped"}
        from ..slack.client import SlackClient
        from ..sources import slack_token
        store = Store(db_path)
        try:
            item = store.get_item(str(item_id))
            gmail = slack = None
            if item is not None and item.source == "slack":
                tok = slack_token(config.settings())
                slack = SlackClient(tok) if tok else None
            elif item is not None:
                try:
                    gmail = GmailClient(action_credentials())
                except AuthError as e:
                    return HTTPStatus.PRECONDITION_FAILED, {"error": str(e)}
            return HTTPStatus.OK, actions.mark_read(store, str(item_id), gmail, slack)
        except actions.ActionError as e:
            return HTTPStatus.CONFLICT, {"error": str(e)}
        finally:
            store.db.close()
    if kind in ("done", "undone"):   # local only: hides in FrontDesk, touches no mailbox
        store = Store(db_path)
        try:
            return HTTPStatus.OK, actions.set_done(store, str(item_id), kind == "done")
        except actions.ActionError as e:
            return HTTPStatus.CONFLICT, {"error": str(e)}
        finally:
            store.db.close()
    if kind in ("star", "unstar"):
        # Gmail: the STARRED label, through the actions token. Slack: local only, no token.
        store = Store(db_path)
        try:
            item = store.get_item(item_id)
            gmail = None
            if item is not None and item.source == "gmail" and not settings.get("demo"):
                try:
                    gmail = GmailClient(action_credentials())
                except AuthError as e:
                    return HTTPStatus.PRECONDITION_FAILED, {"error": str(e)}
            return HTTPStatus.OK, actions.set_starred(store, item_id, kind == "star", gmail, key)
        except actions.ActionError as e:
            return HTTPStatus.CONFLICT, {"error": str(e)}
        finally:
            store.db.close()
    if kind == "relabel":   # local only: no Gmail token needed
        store = Store(db_path)
        try:
            return HTTPStatus.OK, actions.relabel(store, item_id, str(req.get("bucket", "")))
        except actions.ActionError as e:
            return HTTPStatus.CONFLICT, {"error": str(e)}
        finally:
            store.db.close()
    try:
        gmail = None if settings.get("demo") else GmailClient(action_credentials())
    except AuthError as e:
        return HTTPStatus.PRECONDITION_FAILED, {"error": str(e)}
    store = Store(db_path)
    try:
        if kind == "send_prepare":
            from .. import sending
            from ..slack.client import SlackClient
            from ..sources import slack_token
            tok = None if settings.get("demo") else slack_token(config.settings())
            return HTTPStatus.OK, sending.prepare(
                store, item_id, req.get("body"), str(req.get("seen_updated_at", "")), gmail,
                key, slack=SlackClient(tok) if tok else None,
                reply_all=req.get("reply_all") is True)
        if kind == "draft":
            return HTTPStatus.OK, actions.save_draft(store, item_id, req.get("body"),
                                                     str(req.get("seen_updated_at", "")),
                                                     gmail, key,
                                                     reply_all=req.get("reply_all") is True)
        if kind == "inbox":
            return HTTPStatus.OK, actions.move_to_inbox(store, item_id, gmail, key)
        return HTTPStatus.OK, actions.set_archived(store, item_id, kind == "archive", gmail, key)
    except actions.ActionError as e:
        return HTTPStatus.CONFLICT, {"error": str(e)}
    finally:
        store.db.close()


def available_models(settings: dict) -> list[dict]:
    """The Ask model list, minus vendors with no key configured."""
    from ..providers import has_key
    have: dict[str, bool] = {}
    out = []
    for m in settings["ask_models"]:
        if m["provider"] not in have:
            have[m["provider"]] = has_key(settings, m["provider"])
        if have[m["provider"]]:
            out.append(m)
    return out


def ask_all(db_path: Path, settings: dict, models: list[dict], item_id: str,
            question: str, author: str) -> dict:
    """The same question to every available model in parallel, each answer saved under its
    model's label. A model that fails is reported, not fatal. The question is recorded once,
    with its author."""
    from concurrent.futures import ThreadPoolExecutor

    from .. import assist
    from ..providers import ProviderError, get_provider
    q = (question or "").strip() or assist.ADVISE
    store = Store(db_path)
    try:
        store.add_ask(item_id, "owner", q + "  [asked: all models]", author)
    finally:
        store.db.close()

    def one(m: dict) -> dict:
        st = Store(db_path)      # one connection per thread (sqlite)
        try:
            s = {**settings, "provider": m["provider"], "model": m["model"]}
            return assist.ask(st, get_provider(s), item_id, q, settings["owner_profile"],
                              author=author, record_question=False,
                              signoff=settings.get("reply_signoff", ""), label=m["label"])
        except ProviderError as e:
            return {"model": m["label"], "error": str(e)}
        finally:
            st.db.close()
    with ThreadPoolExecutor(max_workers=max(1, len(models))) as pool:
        answers = list(pool.map(one, models))
    return {"answers": answers}


def host_allowed(host_header: str, extra_names: set[str]) -> bool:
    host = host_header.strip().lower()
    if host.startswith("["):                       # [::1]:8765
        host = host[1:host.find("]")] if "]" in host else ""
    elif host.count(":") == 1:                     # name:port or v4:port
        host = host.split(":", 1)[0]
    if not host:
        return False
    if host == "localhost" or host in extra_names:
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def load_token(home: Path) -> str:
    """A per-install random token, created once with mode 0600 so the printed link keeps working
    across restarts. Delete the file to rotate it."""
    path = home / "serve_token"
    if path.exists():
        return path.read_text().strip()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    tok = secrets.token_urlsafe(24)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
        f.write(tok)
    return tok


def make_handler(db_path: Path, settings: dict | None = None, token: str | None = None,
                 extra_hosts: set[str] | None = None) -> type[BaseHTTPRequestHandler]:
    names = {h.lower() for h in (extra_hosts or set())}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes = b"", ctype: str = "",
                  extra: dict[str, str] | None = None, csp: str = CSP) -> None:
            self.send_response(status)
            if ctype:
                self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", csp)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _authorized(self) -> bool:
            if token is None:
                return True
            jar = SimpleCookie(self.headers.get("Cookie", ""))
            got = jar[COOKIE].value if COOKIE in jar else ""
            return secrets.compare_digest(got, token)

        def _gate(self) -> bool:
            """Host allowlist, then token. Returns False after answering the request itself."""
            if not host_allowed(self.headers.get("Host", ""), names):
                self._send(HTTPStatus.FORBIDDEN, b"Forbidden\n", TEXT)
                return False
            path, _, query = self.path.partition("?")
            if token is not None and path == "/index.html":
                offered = parse_qs(query).get("token", [""])[0]
                if offered and secrets.compare_digest(offered, token):
                    self._send(HTTPStatus.FOUND, extra={
                        "Location": "/index.html",
                        "Set-Cookie": f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict"})
                    return False
            if not self._authorized():
                self._send(HTTPStatus.UNAUTHORIZED,
                           b"Open the link 'frontdesk serve' printed; it carries a token.\n", TEXT)
                return False
            return True

        def do_GET(self) -> None:
            if not self._gate():
                return
            path, _, query = self.path.partition("?")
            if path == "/":
                self._send(HTTPStatus.FOUND, extra={"Location": "/index.html"})
            elif path in STATIC:
                name, ctype = STATIC[path]
                self._send(HTTPStatus.OK, (STATIC_DIR / name).read_bytes(), ctype)
            elif path == "/api/profile":
                # The profile plus "What's going on". The demo shows both empty and read-only.
                demo = bool((settings or {}).get("demo"))
                cfg = {} if demo else config.settings()
                prof, sign = cfg.get("owner_profile", ""), cfg.get("reply_signoff", "")
                situation: list[dict] = []
                if not demo:
                    store = Store(db_path)
                    try:
                        situation = store.situation()
                    finally:
                        store.db.close()
                body = {"profile": prof, "signoff": sign, "demo": demo, "situation": situation}
                self._send(HTTPStatus.OK, json.dumps(body).encode(),
                           "application/json; charset=utf-8")
            elif path in ("/api/memory", "/api/memory/export"):
                demo = bool((settings or {}).get("demo"))
                if demo and path.endswith("/export"):
                    self._send(HTTPStatus.NOT_FOUND, b"Not found\n", TEXT)
                    return
                body = DEMO_MEMORY
                if not demo:
                    store = Store(db_path)
                    try:
                        body = memory_export(store) if path.endswith("/export") \
                            else memory_payload(store)
                    finally:
                        store.db.close()
                extra = {"Content-Disposition": 'attachment; filename="frontdesk-memory.json"'} \
                    if path.endswith("/export") else None
                self._send(HTTPStatus.OK, json.dumps(body, indent=1).encode(),
                           "application/json; charset=utf-8", extra=extra)
            elif path == "/api/ask":
                item_id = parse_qs(query).get("item", [""])[0]
                store = Store(db_path)
                try:
                    item = store.get_item(item_id)
                    out = None if item is None else ask_payload(store, item)
                finally:
                    store.db.close()
                if out is None:
                    self._send(HTTPStatus.NOT_FOUND, b"Not found\n", TEXT)
                else:
                    self._send(HTTPStatus.OK, json.dumps(out).encode(),
                               "application/json; charset=utf-8")
            elif path == "/api/search/thread":
                code, out = search_thread(settings or {}, parse_qs(query).get("id", [""])[0])
                self._send(code, json.dumps(out).encode(), "application/json; charset=utf-8")
            elif path == "/api/search":
                code, out = run_search(settings or {}, parse_qs(query).get("q", [""])[0],
                                       db_path=db_path)
                self._send(code, json.dumps(out).encode(), "application/json; charset=utf-8")
            elif path == "/api/gmail-draft":
                code, out = gmail_draft(db_path, settings or {},
                                        parse_qs(query).get("item", [""])[0])
                self._send(code, json.dumps(out).encode(), "application/json; charset=utf-8")
            elif path == "/api/models":
                body = [{"index": i, "label": m["label"], "provider": m["provider"]}
                        for i, m in enumerate(available_models(config.settings()))]
                self._send(HTTPStatus.OK, json.dumps(body).encode(),
                           "application/json; charset=utf-8")
            elif path == "/api/status":
                # slack: Slack has been synced into this store (hidden threads count too), so the
                # page knows to search it before any Slack thread is on screen.
                store = Store(db_path)
                try:
                    slack = store.db.execute(
                        "SELECT 1 FROM items WHERE source='slack' LIMIT 1").fetchone() is not None
                finally:
                    store.db.close()
                self._send(HTTPStatus.OK, json.dumps({**_last_sync, "slack": slack}).encode(),
                           "application/json; charset=utf-8")
            elif path == "/api/send-status":
                from .. import actions, sending
                q = parse_qs(query)
                sid = q.get("id", [""])[0]
                store = Store(db_path)
                try:
                    out = sending.status(store, int(sid)) if sid.isdigit() else None
                except actions.ActionError:
                    out = None
                finally:
                    store.db.close()
                if out is None:
                    self._send(HTTPStatus.NOT_FOUND, b"Not found\n", TEXT)
                else:
                    self._send(HTTPStatus.OK, json.dumps(out).encode(),
                               "application/json; charset=utf-8")
            elif path == "/api/items":
                # A fresh Store per request: sqlite3 connections refuse cross-thread use by
                # default and ThreadingHTTPServer runs each request on its own thread.
                store = Store(db_path)
                try:
                    # Read per request so a sign-off edited in the profile applies at once.
                    sign = "" if (settings or {}).get("demo") else \
                        config.settings()["reply_signoff"]
                    body = json.dumps(ranked_payload(store, sign)).encode()
                finally:
                    store.db.close()
                self._send(HTTPStatus.OK, body, "application/json; charset=utf-8")
            elif path == "/msg":
                q = parse_qs(query)
                i = q.get("i", [""])[0]
                store = Store(db_path)
                try:
                    doc = message_html(store, q.get("item", [""])[0], int(i)) \
                        if i.isdigit() else None
                finally:
                    store.db.close()
                if doc is None:
                    self._send(HTTPStatus.NOT_FOUND, b"Not found\n", TEXT)
                else:
                    self._send(HTTPStatus.OK, doc.encode(), "text/html; charset=utf-8",
                               csp=MSG_CSP)
            else:
                self._send(HTTPStatus.NOT_FOUND, b"Not found\n", TEXT)

        do_HEAD = do_GET

        def do_POST(self) -> None:
            if not self._gate():
                return
            # CSRF: a cross-site page can't send a custom header without a CORS preflight,
            # which this server never answers, and a browser always sends Origin on POST.
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            routes = {"/api/sync": "sync", "/api/action": "action"}
            if (routes.get(self.path) is None
                    or self.headers.get("X-FrontDesk") != routes[self.path]
                    or (origin is not None and origin != f"http://{host}")):
                self._send(HTTPStatus.FORBIDDEN, b"Forbidden\n", TEXT)
                return
            # Re-read settings per request (except the demo's fixed ones), so an edit to
            # settings.json, e.g. the owner profile, applies on the next Sync without a restart.
            s = settings if (settings or {}).get("demo") else config.settings()
            if self.path == "/api/sync":
                status, out = run_sync(db_path, s)
            else:
                n = int(self.headers.get("Content-Length") or 0)
                if not 0 < n <= 65536 or "application/json" not in \
                        self.headers.get("Content-Type", ""):
                    self._send(HTTPStatus.BAD_REQUEST, b"Bad request\n", TEXT)
                    return
                try:
                    req = json.loads(self.rfile.read(n))
                except ValueError:
                    self._send(HTTPStatus.BAD_REQUEST, b"Bad request\n", TEXT)
                    return
                status, out = run_action(db_path, s, req if isinstance(req, dict) else {})
            self._send(status, json.dumps(out).encode(), "application/json; charset=utf-8")

        def log_message(self, fmt: str, *args) -> None:
            pass  # never log request lines: paths carry message ids

    return Handler


def _tailscale_ip() -> str | None:
    exe = shutil.which("tailscale")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.split()[0] if r.returncode == 0 and r.stdout.strip() else None


def make_server(store: Store, host: str, port: int, settings: dict | None = None,
                token: str | None = None) -> ThreadingHTTPServer:
    extra = set((settings or {}).get("serve_allowed_hosts", []))
    return ThreadingHTTPServer((host, port), make_handler(store.path, settings, token, extra))


def start_dispatcher(db_path: Path, interval: float = 2.0) -> threading.Thread:
    """Sends confirmed replies once their undo window passes. One loop per server; the claim in
    sending.dispatch_due makes a second loop (or a cancel) safe anyway."""
    from .. import sending
    from ..gmail.auth import action_credentials
    from ..gmail.client import GmailClient
    clients: dict = {}

    def gmail():
        if "gmail" not in clients:
            clients["gmail"] = GmailClient(action_credentials())
        return clients["gmail"]

    def slack():
        if "slack" not in clients:
            from ..slack.client import SlackClient
            from ..sources import slack_token
            tok = slack_token(config.settings())
            if not tok:
                raise RuntimeError("no Slack token")
            clients["slack"] = SlackClient(tok)
        return clients["slack"]

    def loop():
        while True:
            try:
                store = Store(db_path)
                try:
                    sending.dispatch_due(store, gmail, slack_factory=slack)
                finally:
                    store.db.close()
            except Exception as e:  # noqa: BLE001 - keep the loop alive; report the type only
                print(f"send dispatcher: {type(e).__name__}", flush=True)
            threading.Event().wait(interval)

    t = threading.Thread(target=loop, name="send-dispatcher", daemon=True)
    t.start()
    return t


def serve(store: Store, host: str, port: int, settings: dict | None = None) -> None:
    s = settings or {}
    if not s.get("demo"):
        start_dispatcher(store.path)
        start_autosync(store.path, int(s.get("auto_sync_minutes", 0)))
    token = None if host in LOOPBACK else load_token(config.HOME)
    httpd = make_server(store, host, port, s, token)
    shown = host
    if host in ("0.0.0.0", "::", ""):
        shown = s.get("serve_display_host") or _tailscale_ip() or "localhost"
        print("Listening on all interfaces: the link below carries the required token.",
              flush=True)
    url = f"http://{shown}:{httpd.server_address[1]}/index.html"
    print(f"FrontDesk: {url}" + (f"?token={token}" if token else ""), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
