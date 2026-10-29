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


def ranked_payload(store: Store) -> list[dict]:
    """HTML bodies stay out of the list payload (fetched per message from /msg); each
    message carries has_html instead."""
    with_html = store.html_indexes()
    out = []
    for item, tri in store.ranked():
        d = item.to_dict()
        for i, m in enumerate(d["messages"]):
            m.pop("html", None)
            m["has_html"] = i in with_html.get(item.id, set())
        out.append({"item": d, "triage": asdict(tri) if tri else None})
    return out


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
    if kind == "profile":
        item_id = key = ""
    elif kind not in ("archive", "unarchive", "draft", "relabel", "send_prepare", "done",
                      "undone", "read") \
            or not isinstance(item_id, str) or not isinstance(key, str):
        return HTTPStatus.BAD_REQUEST, {"error": "expected {kind, item_id, key}"}
    if kind == "profile":   # the owner's own words for the model; local settings only
        text = req.get("text")
        if settings.get("demo"):
            return HTTPStatus.CONFLICT, {"error": "Demo mode: the profile can't be changed."}
        if not isinstance(text, str) or len(text) > config.PROFILE_MAX:
            return HTTPStatus.BAD_REQUEST, {"error": f"profile must be text, at most "
                                                     f"{config.PROFILE_MAX} characters"}
        config.save_setting("owner_profile", text.strip())
        return HTTPStatus.OK, {"status": "done", "kind": "profile"}
    if kind == "read":
        if settings.get("demo") or not config.settings()["mark_read_on_open"]:
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
                key, slack=SlackClient(tok) if tok else None)
        if kind == "draft":
            return HTTPStatus.OK, actions.save_draft(store, item_id, req.get("body"),
                                                     str(req.get("seen_updated_at", "")),
                                                     gmail, key)
        return HTTPStatus.OK, actions.set_archived(store, item_id, kind == "archive", gmail, key)
    except actions.ActionError as e:
        return HTTPStatus.CONFLICT, {"error": str(e)}
    finally:
        store.db.close()


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
                demo = bool((settings or {}).get("demo"))
                prof = "" if demo else config.settings()["owner_profile"]
                self._send(HTTPStatus.OK, json.dumps({"profile": prof, "demo": demo}).encode(),
                           "application/json; charset=utf-8")
            elif path == "/api/status":
                self._send(HTTPStatus.OK, json.dumps(_last_sync).encode(),
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
                    body = json.dumps(ranked_payload(store)).encode()
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
