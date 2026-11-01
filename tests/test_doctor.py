"""frontdesk doctor: every check, offline, against a temp FRONTDESK_HOME and a fake Keychain;
and it never prints a key."""
from __future__ import annotations

import json

import pytest

from frontdesk import config, doctor
from frontdesk.gmail.auth import ACTION_SCOPES, SCOPES
from frontdesk.providers import VENDORS

KEY = "sk-test-NEVER-PRINTED-0123456789"


@pytest.fixture
def home(tmp_path, monkeypatch):
    for name, value in (("HOME", tmp_path), ("SETTINGS_PATH", tmp_path / "settings.json"),
                        ("GMAIL_CLIENT_SECRET", tmp_path / "client_secret.json"),
                        ("GMAIL_TOKEN", tmp_path / "gmail_token.json"),
                        ("GMAIL_ACTIONS_TOKEN", tmp_path / "gmail_actions_token.json")):
        monkeypatch.setattr(config, name, value)
    return tmp_path


def ready(home):
    (home / "client_secret.json").write_text(json.dumps({"installed": {"client_id": "x"}}))
    (home / "gmail_token.json").write_text(json.dumps({"scopes": SCOPES}))
    (home / "gmail_actions_token.json").write_text(json.dumps({"scopes": ACTION_SCOPES}))


def by_what(results):
    return {c.what.split(" ")[0] if c.what.startswith("Model") else c.what: c for c in results}


def probe_of(answers):
    return lambda service: answers.get(service, "missing")


def test_a_ready_setup_passes_and_says_where_each_key_comes_from(home):
    ready(home)
    env = {"ANTHROPIC_API_KEY": KEY, "SLACK_USER_TOKEN": KEY}
    r = by_what(doctor.checks(environ=env, probe=probe_of({})))
    assert r["Model:"].level == "ok" and "ANTHROPIC_API_KEY" in r["Model:"].detail
    assert r["Slack"].level == "ok" and "channel messages: mentions" in r["Slack"].detail
    assert r["Gmail actions (archive, drafts, send)"].level == "ok"
    assert not [c for c in doctor.checks(environ=env, probe=probe_of({})) if c.level == "fail"]


def test_missing_required_pieces_fail_with_their_fix(home):
    r = by_what(doctor.checks(environ={}, probe=probe_of({})))
    assert r["Gmail OAuth client"].level == "fail" and "Desktop app" in r["Gmail OAuth client"].detail
    assert r["Model:"].level == "fail" and "security add-generic-password" in r["Model:"].detail
    assert r["Gmail read access"].level == "warn" and "frontdesk sync" in r["Gmail read access"].detail
    assert r["Slack"].level == "warn" and "optional" in r["Slack"].detail


def test_a_web_client_json_is_not_a_desktop_client(home):
    ready(home)
    (home / "client_secret.json").write_text(json.dumps({"web": {"client_id": "x"}}))
    assert by_what(doctor.checks(environ={"ANTHROPIC_API_KEY": KEY}, probe=probe_of({})))[
        "Gmail OAuth client"].level == "fail"


def test_a_locked_keychain_is_named_not_reported_missing(home):
    ready(home)
    r = by_what(doctor.checks(environ={}, probe=probe_of({"frontdesk-anthropic": "locked",
                                                         "frontdesk-slack": "locked"})))
    assert r["Model:"].level == "fail" and "locked" in r["Model:"].detail
    assert r["Slack"].level == "warn" and "sync skips Slack here" in r["Slack"].detail


def test_linux_without_a_keychain_points_at_the_environment_variable(home):
    ready(home)
    r = by_what(doctor.checks(environ={}, probe=probe_of({"frontdesk-anthropic": "unavailable"})))
    assert r["Model:"].detail == "no key: set ANTHROPIC_API_KEY"


def test_a_token_with_other_scopes_will_be_discarded(home):
    ready(home)
    (home / "gmail_token.json").write_text(json.dumps({"scopes": ACTION_SCOPES}))
    c = by_what(doctor.checks(environ={"ANTHROPIC_API_KEY": KEY}, probe=probe_of({})))["Gmail read access"]
    assert c.level == "warn" and "discarded" in c.detail


def test_a_bad_setting_fails_and_stops(home):
    (home / "settings.json").write_text(json.dumps({"modle": "x"}))
    r = doctor.checks(environ={}, probe=probe_of({}))
    assert [c.what for c in r] == ["Python", "Settings"] and r[1].level == "fail"
    assert "modle" in r[1].detail


def test_an_old_python_fails(home):
    ready(home)
    r = by_what(doctor.checks(environ={"ANTHROPIC_API_KEY": KEY}, probe=probe_of({}), version=(3, 11, 9)))
    assert r["Python"].level == "fail" and "3.12" in r["Python"].detail


def test_a_chosen_vendor_that_is_not_installed_fails_with_its_extra(home, monkeypatch):
    ready(home)
    (home / "settings.json").write_text(json.dumps({"provider": "openai", "model": "gpt-6.1-sol"}))
    monkeypatch.setattr(doctor, "_installed", lambda module: module != "openai")
    c = by_what(doctor.checks(environ={"OPENAI_API_KEY": KEY}, probe=probe_of({})))["Model:"]
    assert c.level == "fail" and ".[openai]" in c.detail


def test_ask_vendors_without_a_key_only_warn(home):
    ready(home)
    r = by_what(doctor.checks(environ={"ANTHROPIC_API_KEY": KEY}, probe=probe_of({})))
    assert r["Ask: openai"].level == "warn" and "not offered in Ask" in r["Ask: openai"].detail


def test_online_reports_the_workspace_or_a_rejected_token(home):
    ready(home)
    env = {"ANTHROPIC_API_KEY": KEY, "SLACK_USER_TOKEN": KEY}

    class Good:
        def auth_test(self):
            return {"team": "Example Team"}

    class Bad:
        def auth_test(self):
            raise RuntimeError("invalid_auth " + KEY)
    ok = by_what(doctor.checks(environ=env, probe=probe_of({}), online=True, slack_client=Good))
    assert ok["Slack"].level == "ok" and "Example Team" in ok["Slack"].detail
    bad = by_what(doctor.checks(environ=env, probe=probe_of({}), online=True, slack_client=Bad))
    assert bad["Slack"].level == "fail" and KEY not in bad["Slack"].detail


def test_main_never_prints_a_key_and_exits_by_failures(home, monkeypatch):
    ready(home)
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.setenv("SLACK_USER_TOKEN", KEY)
    monkeypatch.setattr(doctor, "keychain_probe", probe_of({}))
    lines: list[str] = []
    assert doctor.main(out=lines.append) == 0
    assert not any(KEY in line for line in lines)
    assert lines[-1].endswith("Ready: frontdesk sync, then frontdesk serve.")


def test_every_vendor_has_an_install_check():
    assert set(doctor.EXTRAS) == set(VENDORS)
