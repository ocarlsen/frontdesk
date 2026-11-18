"""Triage traces: the writer's file handling, what run() records, and the reader command."""
from __future__ import annotations

import json
import os
import stat

import pytest

from frontdesk import traces, triage
from frontdesk.__main__ import main
from frontdesk.providers import Completion, ProviderError, ProviderRefusal, Usage
from frontdesk.store import Store
from tests.test_triage import FakeProvider, item


def mode(p):
    return stat.S_IMODE(p.stat().st_mode)


def rec(n=1, bucket="fyi", version="v1", ts="2026-11-18T10:00:00Z"):
    return {"ts": ts, "item_id": f"gmail:t{n}", "prompt_version": version,
            "model_requested": "fake:fake-1", "model_served": "m", "system": "SYS",
            "user": f"user text {n}", "raw": f"raw text {n}",
            "parsed": {"bucket": bucket, "urgency": 2, "reason": "r", "proposed_reply": "",
                       "summary": "s"},
            "outcome": "ok", "error": ""}


# ---------- writer ----------

def test_created_0600_and_append_only(isolated_home):
    traces.append(rec(1))
    traces.append(rec(2))
    p = traces.path()
    assert p == isolated_home / "traces.jsonl" and mode(p) == 0o600
    assert [json.loads(line)["item_id"] for line in p.read_text().splitlines()] == [
        "gmail:t1", "gmail:t2"]


def test_loose_mode_is_tightened_not_loosened(isolated_home):
    isolated_home.mkdir(mode=0o700)
    p = traces.path()
    p.write_text("")
    os.chmod(p, 0o644)
    traces.append(rec())
    assert mode(p) == 0o600
    os.chmod(p, 0o400)   # stricter than 0600 stays as it is
    traces._tighten(p)
    assert mode(p) == 0o400


def test_rotation_at_the_cap_keeps_0600(isolated_home):
    traces.append(rec(1), max_bytes=400)
    first = traces.path().read_text()
    traces.append(rec(2), max_bytes=400)
    assert traces.rotated_path().read_text() == first and mode(traces.rotated_path()) == 0o600
    assert [json.loads(x)["item_id"] for x in traces.path().read_text().splitlines()] == [
        "gmail:t2"]
    traces.append(rec(3), max_bytes=400)   # replaces the older rotated file
    assert json.loads(traces.rotated_path().read_text())["item_id"] == "gmail:t2"
    assert mode(traces.path()) == 0o600


def test_enabled_is_strict():
    assert traces.enabled({}) is True
    assert traces.enabled({"triage_traces": False}) is False
    with pytest.raises(ValueError, match=r"triage_traces.*'no'"):
        traces.enabled({"triage_traces": "no"})


# ---------- run() ----------

def test_run_writes_ok_refusal_and_error_records(tmp_path):
    class Mixed(FakeProvider):
        def complete_json(self, system, user, schema, max_tokens=2048):
            if "refuse-me" in user:
                raise ProviderRefusal("declined")
            if "break-me" in user:
                raise ProviderError("boom")
            if "bad-shape" in user:
                return Completion({"bucket": "nope"}, Usage(), raw='{"bucket": "nope"}')
            out = json.dumps(self.out)
            return Completion(dict(self.out), Usage(tokens_in=10, tokens_out=5, latency_ms=7,
                                                    model_served="served-1"), raw=out)

    store = Store(tmp_path / "t.db")
    for n, body in enumerate(("fine", "refuse-me", "break-me", "bad-shape"), 1):
        store.upsert_item(item(n, body=body))
    ok, failed = triage.run(store, Mixed(), log=lambda *_: None, traces=True)
    assert (ok, failed) == (1, 3)
    rows = {r["item_id"]: r for r in map(json.loads, traces.path().read_text().splitlines())}
    good = rows["gmail:t1"]
    assert good["outcome"] == "ok" and good["parsed"]["bucket"] == "needs_you"
    assert good["raw"] and "fine" in good["user"]
    assert good["system"].startswith("You triage one conversation")
    assert (good["tokens_in"], good["latency_ms"], good["model_served"]) == (10, 7, "served-1")
    assert good["model_requested"] == "fake:fake-1"
    assert good["prompt_version"] == triage.PROMPT_VERSION and good["ts"].endswith("Z")
    assert rows["gmail:t2"]["outcome"] == "refusal" and rows["gmail:t2"]["error"] == "declined"
    assert rows["gmail:t3"]["outcome"] == "error" and rows["gmail:t3"]["parsed"] is None
    assert "break-me" in rows["gmail:t3"]["user"] and rows["gmail:t3"]["system"]
    assert rows["gmail:t4"]["outcome"] == "error" and rows["gmail:t4"]["raw"] == '{"bucket": "nope"}'


def test_run_default_and_off_switch_write_nothing(tmp_path):
    store = Store(tmp_path / "t.db")
    store.upsert_item(item(1))
    triage.run(store, FakeProvider(), log=lambda *_: None)
    triage.run(store, FakeProvider(), log=lambda *_: None, traces=False)
    assert not traces.path().exists()


def test_evals_do_not_write(tmp_path):
    triage.triage_item(FakeProvider(), item(1))
    assert not traces.path().exists()


def test_triage_item_fills_trace_out_param():
    tr: dict = {}
    triage.triage_item(FakeProvider(), item(1), trace=tr)
    assert set(tr) == {"system", "user", "raw"}


# ---------- reader ----------

def call(capsys, *argv):
    assert main(["traces", *argv]) == 0
    return capsys.readouterr().out


def test_reader_missing_file(capsys):
    out = call(capsys)
    assert "no traces yet" in out and out.count("\n") == 1


def test_reader_filters_limit_and_order(capsys):
    traces.append(rec(1, "fyi", "v1"))
    traces.append(rec(2, "needs_you", "v1"))
    traces.append(rec(3, "needs_you", "v2"))
    out = call(capsys, "--json")
    assert [json.loads(x)["item_id"] for x in out.splitlines()] == [
        "gmail:t3", "gmail:t2", "gmail:t1"]
    assert json.loads(out.splitlines()[0])["model_bucket"] == "needs_you"
    ids = lambda *a: [json.loads(x)["item_id"] for x in call(capsys, "--json", *a).splitlines()]  # noqa: E731
    assert ids("-n", "2") == ["gmail:t3", "gmail:t2"]
    assert ids("--bucket", "needs_you", "--version", "v1") == ["gmail:t2"]
    assert ids("--bucket", "ignore") == []


def test_reader_reaches_into_the_rotated_file(capsys):
    traces.append(rec(1), max_bytes=400)
    traces.append(rec(2), max_bytes=400)
    out = call(capsys, "--json", "-n", "5")
    assert [json.loads(x)["item_id"] for x in out.splitlines()] == ["gmail:t2", "gmail:t1"]


def test_reader_human_format_and_system_flag(capsys):
    traces.append(rec(1))
    out = call(capsys)
    assert out.index("INPUT") < out.index("user text 1") < out.index("RAW OUTPUT")
    assert out.index("RAW OUTPUT") < out.index("raw text 1")
    assert "gmail:t1" in out.splitlines()[1] and "SYS" not in out
    assert "SYSTEM" in call(capsys, "--system")


def test_reader_skips_a_torn_line(capsys):
    traces.append(rec(1))
    with open(traces.path(), "a") as f:
        f.write('{"ts": "tor')
    assert len(call(capsys, "--json").splitlines()) == 1
