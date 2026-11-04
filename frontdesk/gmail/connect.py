"""Connect Gmail from the page: the OAuth consent flow run by the server instead of a terminal.

Two permissions, each its own token file, exactly as the CLI grants them (auth.py): "read"
(gmail.readonly, for sync) and "actions" (gmail.modify, for archive, drafts and send). Connecting
the second stays a separate, explicit step.

Where Google sends the browser back after consent depends on the OAuth client:
- the Desktop client in client_secret.json (what setup creates) may only return to localhost.
  On the computer running FrontDesk that completes by itself; from another device the browser
  lands on its own localhost and shows an error page, and the owner pastes that page's address
  into FrontDesk ("paste" mode), which carries the same code and state;
- an optional Web client in client_secret_web.json returns to FrontDesk's own https address
  (e.g. a Tailscale Serve name), so it completes by itself from any device. Used only when the
  page was opened at https on a name other than localhost.

The callback cannot rely on the page's cookie (it is SameSite=Strict, and Google's redirect is a
cross-site navigation), so the `state` FrontDesk issued when an authorized page started the flow
is what authenticates it: random, single use, and valid for STATE_TTL seconds. PKCE binds the
code to this server's verifier. A token granted with any other scope set is refused, as auth.py
refuses one on load."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from google_auth_oauthlib.flow import Flow

from .. import config
from .auth import ACTION_SCOPES, SCOPES, _load_token, _write_token

STATE_TTL = 600
MAX_PENDING = 8
CALLBACK = "/oauth/callback"
KINDS = {"read": "Gmail", "actions": "Gmail actions (archive, drafts, send)"}


class ConnectError(RuntimeError):
    """A connect step that failed. The message is safe to show the owner."""


def _scopes(kind: str) -> list[str]:
    return {"read": SCOPES, "actions": ACTION_SCOPES}[kind]


def _token_path(kind: str) -> Path:
    return {"read": config.GMAIL_TOKEN, "actions": config.GMAIL_ACTIONS_TOKEN}[kind]


def _kind(kind) -> str:
    if kind not in KINDS:
        raise ConnectError("unknown permission")
    return kind


# state -> (kind, flow, redirect_uri, created). Module-level: one server process, and the flow
# holds the PKCE verifier, which never leaves this process.
_pending: dict[str, tuple[str, Flow, str, float]] = {}
_lock = threading.Lock()
# Bumped on every connect or disconnect, so a long-lived Gmail client (the send dispatcher)
# knows to reload its token.
generation = 0


def status() -> dict:
    """What the page shows, without a network call: per permission, whether a token with the
    right scopes is stored (a revoked one still looks connected until a sync says otherwise),
    and which OAuth clients exist."""
    out = {"desktop_client": config.GMAIL_CLIENT_SECRET.exists(),
           "web_client": config.GMAIL_WEB_CLIENT_SECRET.exists(),
           "generation": generation}   # moves on every connect, so a Reconnect shows too
    for kind in KINDS:
        creds = _load_token(_token_path(kind), _scopes(kind))
        out[kind] = bool(creds and (creds.valid or creds.refresh_token))
    return out


def _host_of(origin: str) -> tuple[str, str]:
    """(scheme, host) of the page's Origin header, e.g. ('https', 'box.tail1.ts.net')."""
    u = urlsplit(origin or "")
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ConnectError("the page's address is unknown; reload FrontDesk and try again")
    return u.scheme, u.netloc


def start(kind, origin: str, serve_port: int) -> dict:
    """Begin a consent flow for `kind` from a page at `origin`. Returns {"url": Google's consent
    page, "mode": "auto" | "paste"}: auto when Google can return to this FrontDesk directly."""
    kind = _kind(kind)
    scheme, netloc = _host_of(origin)
    hostname = urlsplit(origin).hostname or ""
    local = hostname in ("localhost", "127.0.0.1", "::1")
    if scheme == "https" and not local and config.GMAIL_WEB_CLIENT_SECRET.exists():
        secret, mode = config.GMAIL_WEB_CLIENT_SECRET, "auto"
        redirect = f"https://{netloc}{CALLBACK}"
    elif config.GMAIL_CLIENT_SECRET.exists():
        # A Desktop client returns only to localhost: this page's own address when it is local,
        # else the serve port on the device's own localhost, pasted back by hand.
        port = urlsplit(origin).port or serve_port
        redirect = f"http://localhost:{port if local else serve_port}{CALLBACK}"
        secret, mode = config.GMAIL_CLIENT_SECRET, "auto" if local else "paste"
    else:
        raise ConnectError(f"No Google OAuth client at {config.GMAIL_CLIENT_SECRET}. Create a "
                           "Desktop OAuth client in Google Cloud Console and save its JSON there.")
    try:
        flow = Flow.from_client_secrets_file(str(secret), scopes=_scopes(kind),
                                             redirect_uri=redirect)
    except (ValueError, OSError) as e:
        raise ConnectError(f"The OAuth client file {secret.name} could not be read "
                           f"({type(e).__name__}).") from e
    url, state = flow.authorization_url(access_type="offline", prompt="consent",
                                        include_granted_scopes="false")
    with _lock:
        _expire()
        if len(_pending) >= MAX_PENDING:
            raise ConnectError("too many sign-ins in progress; wait a few minutes")
        _pending[state] = (kind, flow, redirect, time.monotonic(), f"{scheme}://{netloc}")
    return {"url": url, "mode": mode, "kind": kind}


def _expire() -> None:
    cutoff = time.monotonic() - STATE_TTL
    for st in [s for s, v in _pending.items() if v[3] < cutoff]:
        del _pending[st]


def finish(query_or_url: str) -> str:
    """Complete a flow from Google's redirect: the callback's query string, or the full address
    the owner pasted. Writes the token and returns the permission kind connected."""
    return finish_with_origin(query_or_url)[0]


def finish_with_origin(query_or_url: str) -> tuple[str, str]:
    """finish(), plus the address of the page that started the flow (its Origin), so the
    callback can link back there: Google returns to localhost, where the page's cookie is not."""
    global generation
    text = (query_or_url or "").strip()
    q = parse_qs(urlsplit(text).query if "?" in text else text)
    state = q.get("state", [""])[0]
    with _lock:
        _expire()
        pending = _pending.pop(state, None) if state else None   # single use, even on failure
    if pending is None:
        raise ConnectError("This sign-in link is unknown or expired. Start again from FrontDesk.")
    kind, flow, _redirect, _, origin = pending
    if q.get("error"):
        raise ConnectError("Google did not grant access (" + q["error"][0][:60] + ").")
    code = q.get("code", [""])[0]
    if not code:
        raise ConnectError("The address has no sign-in code. Copy the whole address and try again.")
    try:
        flow.fetch_token(code=code)
    except Exception as e:  # noqa: BLE001 - oauthlib raises many types; show only the type
        # A scope mismatch (a box unticked on Google's page) surfaces here as a Warning.
        raise ConnectError(f"Google refused the sign-in ({type(e).__name__}). Start again, and "
                           "leave every permission ticked.") from e
    # What Google granted, from its token response (creds.scopes only echoes what was asked).
    granted = flow.oauth2session.token.get("scope") or []
    if isinstance(granted, str):
        granted = granted.split()
    if sorted(granted) != sorted(_scopes(kind)):
        raise ConnectError("Google granted a different permission than FrontDesk asked for; "
                           "start again and leave every permission ticked.")
    creds = flow.credentials
    if not creds.refresh_token:
        raise ConnectError("Google sent no refresh token, so the sign-in would last an hour. "
                           "Remove FrontDesk at myaccount.google.com/permissions, then connect "
                           "again.")
    _write_token(_token_path(kind), creds)
    generation += 1
    return kind, origin


def disconnect(kind) -> None:
    """Delete the local token for `kind`. Google still lists FrontDesk under your account's
    third-party access until you remove it there."""
    global generation
    _token_path(_kind(kind)).unlink(missing_ok=True)
    generation += 1
