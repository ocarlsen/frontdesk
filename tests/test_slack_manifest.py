"""docs/slack-app-manifest.yaml asks for exactly the user scopes FrontDesk's Slack calls need:
a new call in frontdesk/slack/client.py fails here until its scope is in the manifest (and in
METHOD_SCOPES below), and a scope nothing uses fails too."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Each Slack Web API method the client calls, and the user scopes it needs (Slack's method docs).
# conversations.list/info over im, mpim, private and public channels; mark only for DMs.
METHOD_SCOPES = {
    "auth.test": set(),
    "conversations.list": {"channels:read", "groups:read", "im:read", "mpim:read"},
    "conversations.info": {"channels:read", "groups:read", "im:read", "mpim:read"},
    "conversations.history": {"channels:history", "groups:history", "im:history", "mpim:history"},
    "conversations.replies": {"channels:history", "groups:history", "im:history", "mpim:history"},
    "conversations.mark": {"im:write", "mpim:write"},
    "users.info": {"users:read"},
    "chat.postMessage": {"chat:write"},
    "search.messages": {"search:read"},
}


def manifest_user_scopes() -> set[str]:
    lines = (ROOT / "docs" / "slack-app-manifest.yaml").read_text().splitlines()
    i = lines.index("    user:")
    out = set()
    for line in lines[i + 1:]:
        m = re.fullmatch(r"      - ([a-z:.]+)", line)
        if not m:
            break
        out.add(m.group(1))
    return out


def client_methods() -> set[str]:
    src = (ROOT / "frontdesk" / "slack" / "client.py").read_text()
    return set(re.findall(r'"((?:auth|conversations|users|chat|search)\.[a-zA-Z]+)"', src)) | \
        set(re.findall(r'\{BASE\}/([a-z]+\.[a-zA-Z]+)', src))


def test_every_slack_call_has_its_scopes_listed():
    unknown = client_methods() - set(METHOD_SCOPES)
    assert not unknown, f"add these Slack methods to METHOD_SCOPES and the manifest: {unknown}"


def test_the_manifest_asks_for_exactly_what_the_calls_need():
    needed = set().union(*(METHOD_SCOPES[m] for m in client_methods()))
    assert manifest_user_scopes() == needed


def test_the_manifest_has_no_bot():
    text = (ROOT / "docs" / "slack-app-manifest.yaml").read_text()
    assert "bot:" not in text and "bot_user" not in text


def test_the_readme_link_carries_the_same_manifest():
    from urllib.parse import parse_qs, urlparse
    readme = (ROOT / "README.md").read_text()
    links = re.findall(r"\((https://api\.slack\.com/apps\?new_app=1&manifest_yaml=[^)\s]+)\)", readme)
    assert len(links) == 1
    linked = parse_qs(urlparse(links[0]).query)["manifest_yaml"][0]
    text = (ROOT / "docs" / "slack-app-manifest.yaml").read_text().splitlines()
    assert linked == "\n".join(line for line in text if not line.startswith("#"))
