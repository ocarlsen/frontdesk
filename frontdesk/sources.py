"""Sync every configured source. Gmail is required; Slack runs when a user token is available
(SLACK_USER_TOKEN, or the macOS Keychain item named by slack_keychain_service) and is skipped,
not failed, when none is configured."""
from __future__ import annotations

import os
import shutil
import subprocess

from .gmail.sync import SyncResult
from .gmail.sync import sync as gmail_sync
from .store import Store


def slack_token(settings: dict) -> str | None:
    tok = os.environ.get("SLACK_USER_TOKEN", "").strip()
    if tok:
        return tok
    if not shutil.which("security"):
        return None
    r = subprocess.run(["security", "find-generic-password", "-s",
                        settings["slack_keychain_service"], "-w"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


def sync_all(store: Store, settings: dict, log=print, interactive: bool = True
             ) -> dict[str, SyncResult]:
    out = {"gmail": gmail_sync(store, settings, log=log, interactive=interactive)}
    token = slack_token(settings)
    if token:
        from .slack.sync import sync as slack_sync
        try:
            out["slack"] = slack_sync(store, settings, token, log=log)
        except Exception as e:  # noqa: BLE001 - Slack trouble must not cost the Gmail sync
            log(f"  slack sync failed: {type(e).__name__}: {e}")
    return out
