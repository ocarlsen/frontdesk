"""Paths and settings. All state lives under ~/.frontdesk (override with FRONTDESK_HOME)."""
from __future__ import annotations

import json
import os
from pathlib import Path

HOME = Path(os.environ.get("FRONTDESK_HOME", Path.home() / ".frontdesk"))
DB_PATH = HOME / "frontdesk.db"
SETTINGS_PATH = HOME / "settings.json"
GMAIL_CLIENT_SECRET = HOME / "client_secret.json"
GMAIL_TOKEN = HOME / "gmail_token.json"
GMAIL_ACTIONS_TOKEN = HOME / "gmail_actions_token.json"   # gmail.modify; only actions load it

DEFAULTS = {
    "provider": "anthropic",
    "model": "claude-opus-5-5",   # picked by evals/results/SCOREBOARD.md
    "provider_options": {"anthropic": {"effort": "medium"}},   # per vendor
    "openai_keychain_service": "frontdesk-openai",    # or OPENAI_API_KEY
    "gemini_keychain_service": "frontdesk-gemini",    # or GEMINI_API_KEY
    # Models offered in Ask (shown only when that vendor has a key). Labels are display names.
    "ask_models": [
        {"provider": "anthropic", "model": "claude-opus-5-5", "label": "Opus 5.5"},
        {"provider": "anthropic", "model": "claude-fable-5-1", "label": "Fable 5.1"},
        {"provider": "openai", "model": "gpt-6.1-sol", "label": "GPT-6.1"},
        {"provider": "gemini", "model": "gemini-3.8-flash", "label": "Gemini 3.8 Flash"},
    ],
    "review_model": "claude-fable-5-1",   # Ask's Second opinion and Polish draft
    "owner_profile": "",   # a few sentences on what matters to you; added to the model's prompt
    "reply_signoff": "",   # e.g. "Best,\nAlex": ends every suggested email reply (not Slack)
    "keychain_service": "frontdesk-anthropic",
    "gmail_query": "in:inbox newer_than:7d",
    "gmail_max_threads": 100,
    "slack_keychain_service": "frontdesk-slack",   # or set SLACK_USER_TOKEN
    "slack_days": 7,
    "slack_max_items": 60,
    "serve_host": "127.0.0.1",
    "serve_port": 8765,
    "auto_sync_minutes": 15,    # the server syncs and ranks on its own; 0 turns it off
    "mark_read_on_open": True,  # open ~2 s: mark read in Gmail / Slack DMs
    "serve_display_host": "",   # address to print when serve_host is 0.0.0.0
    "serve_allowed_hosts": [],  # extra Host names to accept besides localhost and IP literals
    # Optional, only for `frontdesk unanswered` (read-only IMAP, headers only, no model):
    "imap_account": "",            # your Gmail address: the IMAP login and "you"; or IMAP_ACCOUNT
    "imap_keychain_service": "",   # Keychain item (account = imap_account) holding a Gmail app
                                   # password; or set IMAP_APP_PASSWORD
    "imap_host": "imap.gmail.com",
    # Senders `frontdesk unanswered` never lists: addresses or domains ("@example.org").
    "unanswered_ignore_senders": [],
}


def settings() -> dict:
    """DEFAULTS overlaid with settings.json. A malformed or unknown setting raises rather than
    silently falling back, so a typo never quietly runs the wrong model."""
    s = dict(DEFAULTS)
    if SETTINGS_PATH.exists():
        s.update(json.loads(SETTINGS_PATH.read_text()))
    unknown = set(s) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"{SETTINGS_PATH}: unknown setting(s) {sorted(unknown)}")
    return s


PROFILE_MAX = 2000
SIGNOFF_MAX = 200


def save_setting(key: str, value) -> None:
    """Update one key in settings.json, keeping the others; written 0600 via an atomic rename."""
    if key not in DEFAULTS:
        raise ValueError(f"unknown setting {key!r}")
    ensure_home()
    current = json.loads(SETTINGS_PATH.read_text()) if SETTINGS_PATH.exists() else {}
    current[key] = value
    tmp = SETTINGS_PATH.with_name(SETTINGS_PATH.name + ".tmp")
    tmp.unlink(missing_ok=True)
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
        f.write(json.dumps(current, indent=2) + "\n")
    os.replace(tmp, SETTINGS_PATH)


def ensure_home() -> None:
    HOME.mkdir(mode=0o700, parents=True, exist_ok=True)
