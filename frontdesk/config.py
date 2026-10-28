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
    "provider_options": {"effort": "medium"},
    "owner_profile": "",   # a few sentences on what matters to you; added to the model's prompt
    "keychain_service": "frontdesk-anthropic",
    "gmail_query": "in:inbox newer_than:7d",
    "gmail_max_threads": 100,
    "serve_host": "127.0.0.1",
    "serve_port": 8765,
    "serve_display_host": "",   # address to print when serve_host is 0.0.0.0
    "serve_allowed_hosts": [],  # extra Host names to accept besides localhost and IP literals
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


def ensure_home() -> None:
    HOME.mkdir(mode=0o700, parents=True, exist_ok=True)
