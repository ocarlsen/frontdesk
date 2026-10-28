"""Gmail OAuth for a single local user. Phase A reads mail and never changes it, so the only
scope is gmail.readonly: a token that cannot send or modify is the cheapest guarantee that a
bug (or a prompt-injected model) cannot act on the mailbox. Widening scope is a deliberate,
reviewed change to SCOPES, and a stored token with any other scope set is discarded."""
from __future__ import annotations

import json
import os
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from .. import config

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class AuthError(RuntimeError):
    pass


def _stored_scopes(path: Path) -> list[str] | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    scopes = data.get("scopes")
    if isinstance(scopes, str):
        scopes = scopes.split()
    return scopes if isinstance(scopes, list) else None


def _load_token(path: Path) -> Credentials | None:
    if not path.exists():
        return None
    if sorted(_stored_scopes(path) or []) != sorted(SCOPES):
        return None
    try:
        return Credentials.from_authorized_user_file(str(path), SCOPES)
    except (ValueError, KeyError):
        return None


def _write_token(path: Path, creds: Credentials) -> None:
    """Write via a fresh 0600 temp file then rename, so the token is never readable by others,
    even for an instant, and a pre-existing file's looser mode is not inherited."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(creds.to_json())
    os.replace(tmp, path)


def _run_flow(secret: Path) -> Credentials:
    if not secret.exists():
        raise AuthError(
            f"Gmail OAuth client secret not found at {secret}. Create a Desktop OAuth client in "
            "Google Cloud Console and save its JSON there."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    return flow.run_local_server(port=0, open_browser=True)


def credentials(token_path: Path | None = None, secret_path: Path | None = None,
                interactive: bool = True) -> Credentials:
    token_path = token_path or config.GMAIL_TOKEN
    secret_path = secret_path or config.GMAIL_CLIENT_SECRET
    creds = _load_token(token_path)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:  # revoked or expired refresh token: fall through to fresh consent
            creds = None
        if creds and creds.valid:
            _write_token(token_path, creds)
            return creds
    if not interactive:
        raise AuthError("Gmail sign-in needed. Run 'bin/frontdesk sync' in a Terminal once.")
    creds = _run_flow(secret_path)
    _write_token(token_path, creds)
    return creds
