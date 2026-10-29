"""Every test runs against a throwaway FRONTDESK home, never the developer's real ~/.frontdesk
(settings, tokens, database)."""
from __future__ import annotations

import pytest

from frontdesk import config


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "fdhome"
    monkeypatch.setattr(config, "HOME", home)
    for name, leaf in (("DB_PATH", "frontdesk.db"), ("SETTINGS_PATH", "settings.json"),
                       ("GMAIL_CLIENT_SECRET", "client_secret.json"),
                       ("GMAIL_TOKEN", "gmail_token.json"),
                       ("GMAIL_ACTIONS_TOKEN", "gmail_actions_token.json")):
        monkeypatch.setattr(config, name, home / leaf)
    return home
