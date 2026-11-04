"""Connect Gmail from the page, with a fake Google: which client and return address each page
address gets, the single-use state, the scope and refresh-token checks, disconnect, and the
callback route that works without the page cookie but not without a state FrontDesk issued."""
from __future__ import annotations

import json
import stat
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest
from google.oauth2.credentials import Credentials

from frontdesk import config
from frontdesk.gmail import connect
from frontdesk.gmail.auth import ACTION_SCOPES
from frontdesk.store import Store
from frontdesk.web import server as srv

DESKTOP = {"installed": {"client_id": "desk", "client_secret": "x", "token_uri": "https://t",
                         "auth_uri": "https://a", "redirect_uris": ["http://localhost"]}}
WEB = {"web": {"client_id": "web", "client_secret": "x", "token_uri": "https://t",
               "auth_uri": "https://a"}}


class FakeFlow:
    made: list = []
    grant: list | None = None          # scopes Google grants; None = what was asked
    refresh = "r1"

    def __init__(self, secret, scopes, redirect_uri):
        self.secret, self.scopes, self.redirect_uri = secret, scopes, redirect_uri
        self.oauth2session = SimpleNamespace(token={})
        self.codes = []

    @classmethod
    def from_client_secrets_file(cls, secret, scopes, redirect_uri):
        f = cls(secret, scopes, redirect_uri)
        cls.made.append(f)
        return f

    def authorization_url(self, **kw):
        self.kw = kw
        state = f"state{len(self.made)}"
        return f"https://accounts.example/auth?state={state}", state

    def fetch_token(self, code):
        if code == "bad":
            raise ValueError("invalid_grant")
        self.codes.append(code)
        g = self.scopes if self.grant is None else self.grant
        self.oauth2session.token = {"scope": " ".join(g), "access_token": "a"}

    @property
    def credentials(self):
        return Credentials("a", refresh_token=self.refresh, token_uri="https://t",
                           client_id="desk", client_secret="x", scopes=self.scopes)


@pytest.fixture(autouse=True)
def fake_google(monkeypatch):
    FakeFlow.made, FakeFlow.grant, FakeFlow.refresh = [], None, "r1"
    monkeypatch.setattr(connect, "Flow", FakeFlow)
    connect._pending.clear()
    config.HOME.mkdir(parents=True, exist_ok=True)
    config.GMAIL_CLIENT_SECRET.write_text(json.dumps(DESKTOP))


def state_of(out):
    return out["url"].rsplit("state=", 1)[1]


def test_page_address_picks_the_client_and_where_google_returns():
    out = connect.start("read", "http://localhost:8765", 8765)
    assert out["mode"] == "auto"
    assert FakeFlow.made[-1].redirect_uri == "http://localhost:8765/oauth/callback"
    assert FakeFlow.made[-1].kw["access_type"] == "offline"
    # another device, Desktop client only: back to that device's localhost, pasted by hand
    out = connect.start("read", "https://box.tail1.ts.net", 8765)
    assert out["mode"] == "paste"
    assert FakeFlow.made[-1].redirect_uri == "http://localhost:8765/oauth/callback"
    assert FakeFlow.made[-1].secret == str(config.GMAIL_CLIENT_SECRET)
    # with a Web client, https on a real name returns to FrontDesk itself
    config.GMAIL_WEB_CLIENT_SECRET.write_text(json.dumps(WEB))
    out = connect.start("actions", "https://box.tail1.ts.net", 8765)
    assert out["mode"] == "auto"
    f = FakeFlow.made[-1]
    assert f.redirect_uri == "https://box.tail1.ts.net/oauth/callback"
    assert f.secret == str(config.GMAIL_WEB_CLIENT_SECRET) and f.scopes == ACTION_SCOPES
    # plain http on a name still uses the Desktop client (Google wants https for a Web client)
    assert connect.start("read", "http://box:8765", 8765)["mode"] == "paste"


def test_start_refusals():
    with pytest.raises(connect.ConnectError, match="unknown permission"):
        connect.start("everything", "http://localhost:8765", 8765)
    with pytest.raises(connect.ConnectError, match="address is unknown"):
        connect.start("read", "", 8765)
    config.GMAIL_CLIENT_SECRET.unlink()
    with pytest.raises(connect.ConnectError, match="No Google OAuth client"):
        connect.start("read", "http://localhost:8765", 8765)


def test_finish_writes_a_private_token_once():
    gen = connect.generation
    out = connect.start("read", "http://localhost:8765", 8765)
    st = state_of(out)
    assert connect.status()["read"] is False
    assert connect.finish(f"state={st}&code=c1") == "read"
    assert FakeFlow.made[-1].codes == ["c1"]
    assert stat.S_IMODE(config.GMAIL_TOKEN.stat().st_mode) == 0o600
    s = connect.status()
    assert s["read"] is True and s["actions"] is False and s["generation"] == gen + 1
    with pytest.raises(connect.ConnectError, match="unknown or expired"):
        connect.finish(f"state={st}&code=c1")                        # single use


def test_finish_accepts_the_pasted_address():
    st = state_of(connect.start("actions", "https://box.tail1.ts.net", 8765))
    pasted = f"  http://localhost:8765/oauth/callback?state={st}&code=c2&scope=x  "
    assert connect.finish(pasted) == "actions"
    assert connect.status()["actions"] is True


@pytest.mark.parametrize("query, match", [
    ("state=nope&code=c", "unknown or expired"),
    ("code=c", "unknown or expired"),
    ("state={st}&error=access_denied", "did not grant"),
    ("state={st}", "no sign-in code"),
    ("state={st}&code=bad", "refused the sign-in"),
])
def test_finish_refusals_write_nothing_and_burn_the_state(query, match):
    st = state_of(connect.start("read", "http://localhost:8765", 8765))
    with pytest.raises(connect.ConnectError, match=match):
        connect.finish(query.format(st=st))
    assert not config.GMAIL_TOKEN.exists()
    if "{st}" in query:   # a failed attempt cannot be retried with the same state
        with pytest.raises(connect.ConnectError, match="unknown or expired"):
            connect.finish(f"state={st}&code=c")


def test_a_different_scope_or_no_refresh_token_is_refused():
    FakeFlow.grant = ACTION_SCOPES                       # asked read-only, got modify
    st = state_of(connect.start("read", "http://localhost:8765", 8765))
    with pytest.raises(connect.ConnectError, match="different permission"):
        connect.finish(f"state={st}&code=c")
    FakeFlow.grant, FakeFlow.refresh = None, None
    st = state_of(connect.start("read", "http://localhost:8765", 8765))
    with pytest.raises(connect.ConnectError, match="no refresh token"):
        connect.finish(f"state={st}&code=c")
    assert not config.GMAIL_TOKEN.exists()


def test_state_expires(monkeypatch):
    st = state_of(connect.start("read", "http://localhost:8765", 8765))
    later = connect.time.monotonic() + connect.STATE_TTL + 1
    monkeypatch.setattr(connect.time, "monotonic", lambda: later)
    with pytest.raises(connect.ConnectError, match="unknown or expired"):
        connect.finish(f"state={st}&code=c")


def test_pending_sign_ins_are_capped():
    for _ in range(connect.MAX_PENDING):
        connect.start("read", "http://localhost:8765", 8765)
    with pytest.raises(connect.ConnectError, match="too many"):
        connect.start("read", "http://localhost:8765", 8765)


def test_disconnect_deletes_only_that_token():
    for kind in ("read", "actions"):
        connect.finish(f"state={state_of(connect.start(kind, 'http://localhost:1', 1))}&code=c")
    gen = connect.generation
    connect.disconnect("actions")
    s = connect.status()
    assert s["read"] is True and s["actions"] is False and s["generation"] == gen + 1
    assert config.GMAIL_TOKEN.exists() and not config.GMAIL_ACTIONS_TOKEN.exists()
    connect.disconnect("actions")                          # already gone: fine
    with pytest.raises(connect.ConnectError):
        connect.disconnect("../settings")


# ---------- HTTP: the callback skips the cookie, nothing else does ----------

@pytest.fixture
def live(tmp_path):
    httpd = srv.make_server(Store(tmp_path / "s.db"), "127.0.0.1", 0, settings={},
                            token="t0ken")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield base
    httpd.shutdown()


def call(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET",
                                 headers=headers or {})
    try:
        r = urllib.request.urlopen(req)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_callback_works_without_the_cookie_only_with_an_issued_state(live):
    st = state_of(connect.start("read", "http://localhost:8765", 8765))
    code, page = call(f"{live}/oauth/callback?state=forged&code=c")
    assert code == 400 and "Not connected" in page and not config.GMAIL_TOKEN.exists()
    code, page = call(f"{live}/oauth/callback?state={st}&code=c")
    assert code == 200 and "Gmail is connected" in page and config.GMAIL_TOKEN.exists()
    # every other route still needs the cookie
    assert call(f"{live}/api/google")[0] == 401
    # and the Host allowlist still applies to the callback
    assert call(f"{live}/oauth/callback?state=x&code=c", headers={"Host": "evil.example"})[0] \
        == 403


def test_callback_page_escapes_googles_error_text(live):
    st = state_of(connect.start("read", "http://localhost:8765", 8765))
    code, page = call(f"{live}/oauth/callback?state={st}&error=%3Cscript%3E")
    assert code == 400 and "<script>" not in page and "&lt;script&gt;" in page


def test_api_needs_cookie_header_and_origin(live):
    host = live.removeprefix("http://")
    ok = {"Cookie": "fd_token=t0ken", "X-FrontDesk": "google",
          "Content-Type": "application/json", "Origin": f"http://{host}"}
    body = json.dumps({"op": "start", "kind": "read"}).encode()
    assert call(f"{live}/api/google", body, {**ok, "Cookie": ""})[0] == 401
    assert call(f"{live}/api/google", body, {**ok, "X-FrontDesk": "action"})[0] == 403
    assert call(f"{live}/api/google", body, {**ok, "Origin": "https://evil.example"})[0] == 403
    code, out = call(f"{live}/api/google", body, ok)
    out = json.loads(out)
    assert code == 200 and out["mode"] == "auto"   # 127.0.0.1 is this machine
    code, out = call(f"{live}/api/google", headers={"Cookie": "fd_token=t0ken"})
    assert code == 200 and json.loads(out)["read"] is False
    st = state_of(connect.start("read", "http://localhost:8765", 8765))
    fin = json.dumps({"op": "finish", "url": f"http://localhost:8765/oauth/callback?state={st}"
                                             "&code=c"}).encode()
    assert call(f"{live}/api/google", fin, ok)[0] == 200 and connect.status()["read"] is True
    off = json.dumps({"op": "disconnect", "kind": "read"}).encode()
    assert call(f"{live}/api/google", off, ok)[0] == 200 and connect.status()["read"] is False
    assert call(f"{live}/api/google", json.dumps({"op": "x"}).encode(), ok)[0] == 400


def test_demo_refuses():
    assert srv.run_google({"demo": True}, {"op": "start", "kind": "read"}, "http://x")[0] == 409
    assert srv.oauth_callback({"demo": True}, "state=x")[0] == 409


def test_callback_links_back_to_the_address_the_owner_started_from(live):
    """Google returns to localhost (a Desktop client), where the page's cookie is not; the
    callback links back to the page's own address instead (seen 2026-11-04)."""
    st = state_of(connect.start("read", "https://box.tail1.ts.net", 8765))
    code, page = call(f"{live}/oauth/callback?state={st}&code=c")
    assert code == 200 and 'href="https://box.tail1.ts.net/index.html"' in page
    assert 'href="/index.html"' not in page
    # a failure has no trusted origin to offer: the relative link stays
    code, page = call(f"{live}/oauth/callback?state=forged&code=c")
    assert code == 400 and 'href="/index.html"' in page
