"""Triage traces: the writer's file handling, what run() records, and the reader command."""
from __future__ import annotations

import json
import os
import stat
import threading

import pytest

from frontdesk import traces, triage
from frontdesk.__main__ import main
from frontdesk.providers import Completion, ProviderError, ProviderRefusal, Usage
from frontdesk.store import Store
from tests.test_triage import FakeProvider, item


def mode(p):
    return stat.S_IMODE(p.stat().st_mode)


def file_rows(p):
    """The records in a trace file, split on newline bytes only (as the reader does)."""
    return [json.loads(x) for x in p.read_bytes().split(b"\n") if x]


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
    assert [r["item_id"] for r in file_rows(p)] == [
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
    assert [r["item_id"] for r in file_rows(traces.path())] == [
        "gmail:t2"]
    traces.append(rec(3), max_bytes=400)   # replaces the older rotated file
    assert json.loads(traces.rotated_path().read_text())["item_id"] == "gmail:t2"
    assert mode(traces.path()) == 0o600


def test_enabled_is_strict():
    assert traces.enabled({}) is False   # off until the owner turns it on: the file holds mail
    assert traces.enabled({"triage_traces": True}) is True
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
    rows = {r["item_id"]: r for r in file_rows(traces.path())}
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


# ---------- review fixes ----------

def test_reader_keeps_records_with_unicode_line_separators(capsys):
    r = rec(1)
    r["user"] = "a\u2028b\u2029c\u0085d"
    traces.append(r)
    traces.append(rec(2))
    out = call(capsys, "--json")
    got = {x["item_id"]: x for x in map(json.loads, out.split("\n")[:-1])}
    assert got["gmail:t1"]["user"] == r["user"] and set(got) == {"gmail:t1", "gmail:t2"}


def test_reader_skips_a_tail_torn_mid_codepoint(capsys):
    traces.append(rec(1))
    with open(traces.path(), "ab") as f:
        f.write('{"user": "caf\u00e9"'.encode()[:-2])   # cuts the two-byte e-acute in half
    assert [r["item_id"] for r in traces.load(5)] == ["gmail:t1"]


def test_append_after_a_torn_tail_starts_a_new_line():
    traces.append(rec(1))
    with open(traces.path(), "ab") as f:
        f.write(b'{"torn')
    traces.append(rec(2))
    assert [r["item_id"] for r in traces.load(5)] == ["gmail:t2", "gmail:t1"]


def test_lone_surrogate_does_not_raise():
    r = rec(1)
    r["user"] = "bad \ud800 text"
    traces.append(r)
    assert traces.load(1)[0]["item_id"] == "gmail:t1"


def test_n_below_one_is_rejected(capsys):
    with pytest.raises(SystemExit):
        main(["traces", "-n", "0"])
    assert "must be 1 or more" in capsys.readouterr().err


def test_non_dict_lines_and_sparse_records_do_not_break_the_reader(capsys):
    traces.append(rec(1))
    with open(traces.path(), "ab") as f:
        f.write(b'[1, 2]\n"str"\n{"item_id": "gmail:t9"}\n')
    assert [r["item_id"] for r in traces.load(9)] == ["gmail:t9", "gmail:t1"]
    out = call(capsys)
    assert "gmail:t9" in out and "gmail:t1" in out


def test_concurrent_appends_across_the_cap_lose_nothing():
    n = 40
    size = len(json.dumps(rec(1))) + 1
    errors = []

    def go(i):
        try:
            traces.append(rec(i), max_bytes=size * 12)
        except Exception as e:   # noqa: BLE001
            errors.append(e)

    ts = [threading.Thread(target=go, args=(i,)) for i in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    ids = {r["item_id"] for r in file_rows(traces.path())}
    ids |= {r["item_id"] for r in file_rows(traces.rotated_path())}
    # one rotation at a time may replace an older rotated file, so check the newest survive
    assert len(file_rows(traces.path())) + len(file_rows(traces.rotated_path())) >= 12
    assert all(mode(p) == 0o600 for p in (traces.path(), traces.lock_path()))
    assert len(ids) == len(file_rows(traces.path())) + len(file_rows(traces.rotated_path()))


def test_malformed_setting_fails_at_load(isolated_home):
    from frontdesk import config
    config.save_setting("triage_traces", "yes")
    with pytest.raises(ValueError, match=r"triage_traces must be true or false, got 'yes'"):
        config.settings()


def test_trace_gets_raw_from_a_failing_provider(tmp_path):
    class Truncated(FakeProvider):
        def complete_json(self, system, user, schema, max_tokens=2048):
            raise ProviderError("hit max_tokens", raw='{"bucket": "fy')

    store = Store(tmp_path / "t.db")
    store.upsert_item(item(1))
    triage.run(store, Truncated(), log=lambda *_: None, traces=True)
    r = file_rows(traces.path())[0]
    assert r["outcome"] == "error" and r["raw"] == '{"bucket": "fy'
