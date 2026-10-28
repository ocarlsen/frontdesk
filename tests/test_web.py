"""Web UI server: routes, headers, JSON shape and order, and the no-innerHTML rule for app.js."""
from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path

import pytest

from frontdesk.items import Item, Message, Triage
from frontdesk.store import Store
from frontdesk.web import server


def _item(n: int, sender: str, updated: str) -> Item:
    return Item(
        id=f"gmail:t{n}", source="gmail", account="owner@example.com",
        subject=f"Subject {n}", participants=[sender, "owner@example.com"],
        messages=[Message(sender=sender, sent_at=updated, body=f"Line one\nLine two {n}")],
        updated_at=updated, url=f"https://mail.google.com/mail/u/0/#inbox/t{n}",
    )


@pytest.fixture
def base(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    # t1 is newer but untriaged; t2 is triaged needs_you, so it must rank first.
    store.upsert_item(_item(1, "Alice <alice@example.com>", "2026-01-02T00:00:00Z"))
    store.upsert_item(_item(2, "Bob <bob@example.com>", "2026-01-01T00:00:00Z"))
    store.save_triage(Triage("gmail:t2", "needs_you", 4, "Asks a direct question",
                             "Sounds good.", "test:model", "2026-01-01T01:00:00Z",
                             "2026-01-01T00:00:00Z"))
    httpd = server.make_server(store, "127.0.0.1", 0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def _get(port: int, path: str) -> http.client.HTTPResponse:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    return conn.getresponse()


def test_api_items_shape_and_order(base):
    r = _get(base, "/api/items")
    assert r.status == 200
    assert r.getheader("Cache-Control") == "no-store"
    rows = json.loads(r.read())
    assert [row["item"]["id"] for row in rows] == ["gmail:t2", "gmail:t1"]
    assert set(rows[0]) == {"item", "triage"}
    assert rows[0]["triage"]["bucket"] == "needs_you"
    assert rows[0]["triage"]["proposed_reply"] == "Sounds good."
    assert rows[1]["triage"] is None
    assert rows[0]["item"]["messages"][0]["body"] == "Line one\nLine two 2"


def test_root_redirects_to_index(base):
    r = _get(base, "/")
    assert r.status == 302
    assert r.getheader("Location") == "/index.html"


def test_index_has_csp(base):
    r = _get(base, "/index.html")
    assert r.status == 200
    csp = r.getheader("Content-Security-Policy")
    assert "default-src 'self'" in csp and "unsafe-inline" not in csp
    assert r.getheader("Cache-Control") == "no-store"
    assert b"<script src=\"app.js\"" in r.read()


def test_static_assets_served(base):
    assert _get(base, "/app.js").status == 200
    assert _get(base, "/app.css").status == 200


def test_unknown_path_404(base):
    assert _get(base, "/nope").status == 404
    assert _get(base, "/../config.py").status == 404


def test_app_js_never_uses_innerhtml():
    js = (Path(server.__file__).parent / "app.js").read_text()
    assert "innerHTML" not in js
    assert "outerHTML" not in js and "insertAdjacentHTML" not in js


def test_msg_route_serves_html_under_strict_csp(tmp_path):
    import urllib.error
    import urllib.request

    from frontdesk.items import Item, Message
    from frontdesk.web.server import make_server, ranked_payload
    store = Store(tmp_path / "m.db")
    store.upsert_item(Item(id="gmail:h1", source="gmail", account="owner@example.com",
                           subject="Hi", participants=["alice@example.com"],
                           messages=[Message("Alice <alice@example.com>", "2026-10-28T16:00:00Z",
                                             "text", html="<b>Hello</b><script>x()</script>")],
                           updated_at="2026-10-28T16:00:00Z"))
    assert ranked_payload(store)[0]["item"]["messages"][0] == {
        "sender": "Alice <alice@example.com>", "sent_at": "2026-10-28T16:00:00Z",
        "body": "text", "is_mine": False, "has_html": True}
    httpd = make_server(store, "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        r = urllib.request.urlopen(base + "/msg?item=gmail%3Ah1&i=0")
        csp = r.headers["Content-Security-Policy"]
        assert "script-src 'none'" in csp and "img-src data:" in csp
        assert b"<b>Hello</b>" in r.read()
        for bad in ("/msg?item=gmail%3Ah1&i=5", "/msg?item=nope&i=0", "/msg?item=gmail%3Ah1&i=x"):
            try:
                urllib.request.urlopen(base + bad)
                raise AssertionError(bad)
            except urllib.error.HTTPError as e:
                assert e.code == 404
    finally:
        httpd.shutdown()


def test_triage_input_excludes_html():
    from frontdesk.items import Item, Message
    from frontdesk.triage import render_user
    it = Item(id="gmail:h", source="gmail", account="o@example.com", subject="s",
              participants=[], updated_at="2026-10-28T16:00:00Z",
              messages=[Message("a@example.com", "2026-10-28T16:00:00Z", "plain",
                                html="<p>SECRET-HTML</p>")])
    assert "SECRET-HTML" not in render_user(it, "2026-10-28")


def test_sync_post_guards(tmp_path, monkeypatch):
    import urllib.error
    import urllib.request

    from frontdesk.web import server as srv
    store = Store(tmp_path / "s.db")
    calls = []
    monkeypatch.setattr(srv, "run_sync",
                        lambda db, s: (calls.append(1) or (200, {"synced": 0, "removed": 0,
                                                                  "triaged": 0, "failed": 0})))
    httpd = srv.make_server(store, "127.0.0.1", 0, settings={})
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def post(path, headers):
        req = urllib.request.Request(base + path, data=b"", method="POST", headers=headers)
        try:
            return urllib.request.urlopen(req).status
        except urllib.error.HTTPError as e:
            return e.code
    try:
        assert post("/api/sync", {}) == 403                                   # no custom header
        assert post("/api/sync", {"X-FrontDesk": "sync",
                                  "Origin": "http://evil.example"}) == 403   # cross-site
        assert post("/api/other", {"X-FrontDesk": "sync"}) == 403
        assert calls == []
        assert post("/api/sync", {"X-FrontDesk": "sync"}) == 200
        assert calls == [1]
    finally:
        httpd.shutdown()


def test_host_allowlist_blocks_rebinding():
    from frontdesk.web.server import host_allowed
    assert host_allowed("127.0.0.1:8765", set())
    assert host_allowed("localhost:8765", set())
    assert host_allowed("[::1]:8765", set())
    assert host_allowed("100.78.1.2:8765", set())
    assert not host_allowed("evil.example:8765", set())
    assert not host_allowed("", set())
    assert host_allowed("mybox:8765", {"mybox"})


def test_token_gate_and_meta_refresh_strip(tmp_path):
    import urllib.error
    import urllib.request

    from frontdesk.items import Item, Message
    from frontdesk.web.server import make_server
    store = Store(tmp_path / "g.db")
    store.upsert_item(Item(id="gmail:m", source="gmail", account="o@example.com", subject="s",
                           participants=[], updated_at="2026-10-28T16:00:00Z",
                           messages=[Message("a@example.com", "2026-10-28T16:00:00Z", "t",
                                             html='<meta http-equiv="refresh" content="0;url='
                                                  'https://track.example/x"><p>hi</p>')]))
    httpd = make_server(store, "127.0.0.1", 0, settings={}, token="sekret")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    opener = urllib.request.build_opener(NoRedirect)

    def get(path, headers=None):
        try:
            r = opener.open(urllib.request.Request(base + path, headers=headers or {}))
            return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, b""
    try:
        assert get("/api/items")[0] == 401
        assert get("/index.html?token=wrong")[0] == 401
        code, hdrs, _ = get("/index.html?token=sekret")
        assert code == 302 and "HttpOnly" in hdrs["Set-Cookie"]
        ck = {"Cookie": "fd_token=sekret"}
        assert get("/api/items", ck)[0] == 200
        assert get("/api/items", {**ck, "Host": "evil.example:1"})[0] == 403
        code, _, body = get("/msg?item=gmail%3Am&i=0", ck)
        assert code == 200 and b"http-equiv" not in body and b"<p>hi</p>" in body
    finally:
        httpd.shutdown()


def test_action_route_guards_and_demo_archive(tmp_path):
    import json as _json
    import urllib.error
    import urllib.request

    from frontdesk.items import Item, Message
    from frontdesk.web.server import make_server
    store = Store(tmp_path / "act.db")
    store.upsert_item(Item(id="gmail:a1", source="gmail", account="o@example.com", subject="s",
                           participants=[], updated_at="2026-10-28T16:00:00Z",
                           messages=[Message("a@example.com", "2026-10-28T16:00:00Z", "t")]))
    httpd = make_server(store, "127.0.0.1", 0, settings={"demo": True})
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def post(body, headers):
        req = urllib.request.Request(base + "/api/action", data=body, method="POST",
                                     headers=headers)
        try:
            r = urllib.request.urlopen(req)
            return r.status, _json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, None
    ok = {"X-FrontDesk": "action", "Content-Type": "application/json"}
    good = _json.dumps({"kind": "archive", "item_id": "gmail:a1", "key": "k" * 16}).encode()
    try:
        assert post(good, {"Content-Type": "application/json"})[0] == 403        # no header
        assert post(good, {**ok, "X-FrontDesk": "sync"})[0] == 403             # wrong route tag
        assert post(good, {"X-FrontDesk": "action"})[0] == 400                 # not JSON
        assert post(b"x" * 70000, ok)[0] == 400                                 # too large
        assert post(_json.dumps({"kind": "delete"}).encode(), ok)[0] == 400     # unknown kind
        code, out = post(good, ok)
        assert code == 200 and out["status"] == "done"
        assert store.ranked() == []
    finally:
        httpd.shutdown()


def test_app_js_wires_the_detail_panels():
    """Guards against an edit silently dropping a panel from the thread view."""
    js = (Path(server.__file__).parent / "app.js").read_text()
    for call in ("d.append(whyPanel(triage))", "saveDraft(item, ta, save)",
                 "archive(item, arch)", 'document.addEventListener("keydown", onKey)'):
        assert call in js, call


def test_profile_read_and_save(tmp_path):
    import json as _json
    import urllib.error
    import urllib.request

    from frontdesk import config
    from frontdesk.web.server import make_server
    config.save_setting("serve_port", 9999)            # an unrelated key must survive a save
    store = Store(tmp_path / "p.db")
    httpd = make_server(store, "127.0.0.1", 0, settings={})
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    hdr = {"X-FrontDesk": "action", "Content-Type": "application/json"}

    def post(body):
        req = urllib.request.Request(base + "/api/action", data=_json.dumps(body).encode(),
                                     method="POST", headers=hdr)
        try:
            return urllib.request.urlopen(req).status
        except urllib.error.HTTPError as e:
            return e.code
    try:
        assert post({"kind": "profile", "text": "I am job hunting."}) == 200
        got = _json.loads(urllib.request.urlopen(base + "/api/profile").read())
        assert got == {"profile": "I am job hunting.", "demo": False}
        assert config.settings()["serve_port"] == 9999
        assert post({"kind": "profile", "text": "x" * 2001}) == 400
        assert oct(config.SETTINGS_PATH.stat().st_mode & 0o777) == "0o600"
    finally:
        httpd.shutdown()
