"""`frontdesk doctor`: what is set up and what is missing, each with the one step that fixes it.

Offline: it reads files under FRONTDESK_HOME, the environment, and (on macOS) whether a Keychain
item exists and can be read, but never prints a key or token. `--online` adds one Slack
auth.test, the only network call. A missing required piece (Python, settings, the Gmail client,
the chosen model's key or install) fails the run; optional pieces only warn."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import config


@dataclass
class Check:
    level: str     # "ok", "warn" (optional or degraded), "fail" (FrontDesk can't run without it)
    what: str
    detail: str


def keychain_probe(service: str) -> str:
    """'found', 'locked' (exists, unreadable from this shell), 'missing', or 'unavailable' (no
    Keychain here). The secret is read only to learn that, and dropped."""
    if not service:
        return "missing"
    if not shutil.which("security"):
        return "unavailable"
    r = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                       capture_output=True, text=True)
    if r.returncode == 36:   # errSecInteractionNotAllowed: the keychain is locked for this shell
        return "locked"
    return "found" if r.returncode == 0 and r.stdout.strip() else "missing"


def secret_source(env_var: str, service: str, environ=os.environ, probe=keychain_probe) -> str:
    """Where a secret would come from: 'env', or keychain_probe's answer for its item."""
    if environ.get(env_var, "").strip():
        return "env"
    return probe(service)


# provider -> (module its adapter imports, pip extra that installs it, or None when it ships with
# FrontDesk). test_doctor checks every vendor in providers.VENDORS has an entry.
EXTRAS = {"anthropic": ("anthropic", None), "openai": ("openai", "openai"),
          "gemini": ("google.genai", "gemini")}


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:   # a missing parent package (google, for google.genai)
        return False


def _key_check(what: str, env_var: str, service: str, source: str, required: bool) -> Check:
    if source == "env":
        return Check("ok", what, f"key from {env_var}")
    if source == "found":
        return Check("ok", what, f"key from Keychain item '{service}'")
    if source == "locked":
        return Check("fail" if required else "warn", what,
                     f"Keychain item '{service}' exists but is locked for this shell (SSH or a "
                     f"tmux started outside the GUI login): run from a regular Terminal, or set "
                     f"{env_var}")
    hint = (f"set {env_var}" if source == "unavailable" else
            f"set {env_var}, or: security add-generic-password -U -s {service} -a $USER -w")
    return Check("fail" if required else "warn", what, f"no key: {hint}")


def _token_check(path: Path, scopes: list[str], what: str, fix: str, required: bool) -> Check:
    if not path.exists():
        return Check("warn" if not required else "fail", what, f"not yet: {fix}")
    try:
        stored = json.loads(path.read_text()).get("scopes")
    except (OSError, ValueError):
        return Check("warn", what, f"unreadable token file {path}: {fix} again")
    stored = stored.split() if isinstance(stored, str) else stored
    if sorted(stored or []) != sorted(scopes):
        return Check("warn", what, f"token has other permissions than FrontDesk asks for, so it "
                                   f"will be discarded: {fix} again")
    return Check("ok", what, "token present")


def checks(environ=os.environ, probe=None, online: bool = False,
           slack_client=None, version=sys.version_info) -> list[Check]:
    from .gmail.auth import ACTION_SCOPES, SCOPES
    probe = probe or keychain_probe
    from .providers import VENDORS
    out: list[Check] = []

    ok_py = tuple(version[:2]) >= (3, 12)
    out.append(Check("ok" if ok_py else "fail", "Python",
                     f"{version[0]}.{version[1]}" + ("" if ok_py else ": FrontDesk needs 3.12")))

    try:
        s = config.settings()
        path = config.SETTINGS_PATH
        n = len(json.loads(path.read_text())) if path.exists() else 0
        out.append(Check("ok", "Settings", f"{n} set in {path}" if n else
                         "defaults (no settings.json)"))
    except ValueError as e:
        out.append(Check("fail", "Settings", str(e)))
        return out

    secret = config.GMAIL_CLIENT_SECRET
    if not secret.exists():
        out.append(Check("fail", "Gmail OAuth client", f"missing {secret}: create a Desktop app "
                         "OAuth client in Google Cloud Console and save its JSON there"))
    else:
        try:
            desktop = "installed" in json.loads(secret.read_text())
        except (OSError, ValueError):
            desktop = False
        out.append(Check("ok", "Gmail OAuth client", "Desktop app client") if desktop else
                   Check("fail", "Gmail OAuth client",
                         f"{secret} is not a Desktop app client JSON"))
    out.append(_token_check(config.GMAIL_TOKEN, SCOPES, "Gmail read access",
                            "run frontdesk sync", required=False))
    out.append(_token_check(config.GMAIL_ACTIONS_TOKEN, ACTION_SCOPES,
                            "Gmail actions (archive, drafts, send)",
                            "frontdesk authorize-actions (optional)", required=False))

    name = s["provider"]
    if name not in VENDORS:
        out.append(Check("fail", "Model",
                         f"unknown provider '{name}' (known: {', '.join(VENDORS)})"))
    else:
        env_var, kc, _ = VENDORS[name]
        module, extra = EXTRAS[name]
        if not _installed(module):
            out.append(Check("fail", f"Model: {name}", f"not installed: .venv/bin/pip install -e "
                             f"'.[{extra}]'" if extra else f"not installed: pip install {module}"))
        else:
            c = _key_check(f"Model: {name} {s['model']}", env_var, s[kc],
                           secret_source(env_var, s[kc], environ, probe), required=True)
            out.append(c)
    others = sorted({m.get("provider") for m in s.get("ask_models", [])} - {name})
    for other in others:
        if other not in VENDORS:
            continue
        env_var, kc, _ = VENDORS[other]
        module, extra = EXTRAS[other]
        if not _installed(module):
            out.append(Check("warn", f"Ask: {other}", f"not offered in Ask (not installed: "
                             f".venv/bin/pip install -e '.[{extra}]')"))
            continue
        c = _key_check(f"Ask: {other}", env_var, s[kc],
                       secret_source(env_var, s[kc], environ, probe), required=False)
        if c.level != "ok":
            c.detail = "not offered in Ask; " + c.detail
        out.append(c)

    src = secret_source("SLACK_USER_TOKEN", s["slack_keychain_service"], environ, probe)
    if src in ("env", "found"):
        item = s["slack_keychain_service"]
        where = "SLACK_USER_TOKEN" if src == "env" else f"Keychain item '{item}'"
        c = Check("ok", "Slack", f"token from {where}; channel messages: "
                  f"{s['slack_channel_messages']}")
        if online:
            try:
                me = (slack_client() if slack_client else _slack_client(s, environ)).auth_test()
                c.detail += f"; signed in to {me.get('team') or me.get('url')}"
            except Exception as e:  # noqa: BLE001 - reported as a check, type only
                c = Check("fail", "Slack", f"token rejected or unreachable ({type(e).__name__})")
        out.append(c)
    elif src == "locked":
        out.append(Check("warn", "Slack", f"Keychain item '{s['slack_keychain_service']}' is "
                         "locked for this shell, so sync skips Slack here: run from a regular "
                         "Terminal, or set SLACK_USER_TOKEN"))
    else:
        out.append(Check("warn", "Slack", "not set up (optional): see the README's Slack step"))
    return out


def _slack_client(s: dict, environ):
    from .slack.client import SlackClient
    from .sources import slack_token
    return SlackClient(environ.get("SLACK_USER_TOKEN", "").strip() or slack_token(s))


MARK = {"ok": "ok  ", "warn": "warn", "fail": "FAIL"}


def main(online: bool = False, out=print) -> int:
    results = checks(online=online)
    width = max(len(c.what) for c in results)
    for c in results:
        out(f"{MARK[c.level]}  {c.what.ljust(width)}  {c.detail}")
    failed = sum(c.level == "fail" for c in results)
    out("\n" + (f"{failed} required piece(s) missing." if failed else
                "Ready: frontdesk sync, then frontdesk serve."))
    return 1 if failed else 0
