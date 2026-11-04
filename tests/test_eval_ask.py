"""The Ask safety eval with fake models: no key, no network, nothing billed."""
from __future__ import annotations

import json
from pathlib import Path

from frontdesk import __main__ as cli
from frontdesk import assist, eval_ask, providers
from frontdesk.providers import Completion, Usage

ROOT = Path(__file__).resolve().parent.parent / "evals"
CASES = eval_ask.load_cases(ROOT)


class Fake:
    """Drafts per case: `leak` puts the first planted string in every injection draft; `invent`
    adds a phone number nothing mentions; otherwise a safe draft that reuses a note's amount."""
    name, model = "fake", "claude-opus-5-5"

    def __init__(self, leak=False, invent=False):
        self.leak, self.invent, self.prompts = leak, invent, []
        self.planted = {c["id"]: c["planted"] for c in CASES}
        self.by_subject = {c["item"].subject: c["id"] for c in CASES}

    def complete_json(self, system, user, schema, max_tokens=2048):
        assert system == assist.SYSTEM and schema == assist.SCHEMA
        self.prompts.append(user)
        draft = "Thanks, I'll get back to you by [date]."
        if "$210k" in user:
            draft = "My floor is $210k base."             # from the owner's own note: allowed
        cid = next((i for subj, i in self.by_subject.items()
                    if json.dumps(subj, ensure_ascii=False).replace("<", "\\u003c") in user), None)
        if self.leak and cid and self.planted[cid]:
            draft += " " + self.planted[cid][0]
        if self.invent:
            draft += " Call me at +1 415 555 0199."
        return Completion({"answer": "Here is what I'd do.", "draft_reply": draft,
                           "note_suggestions": [], "situation_suggestions": []},
                          Usage(tokens_in=1000, tokens_out=100, latency_ms=10,
                                model_served="claude-opus-5-5"))


def test_cases_are_the_existing_fixtures():
    kinds = [c["kind"] for c in CASES]
    assert kinds.count("injection") == 32 and kinds.count("note") == 12
    assert all(c["planted"] for c in CASES if c["kind"] == "injection")
    a02 = next(c for c in CASES if c["id"] == "a02-salary-floor")
    assert "$210k" in a02["known"]                    # the note counts as known


def test_clean_drafts_pass_and_use_the_real_ask_prompt():
    fake = Fake()
    rep = eval_ask.run(fake, ROOT)
    assert rep["pass"] and rep["cases"] == 44 and rep["drafts"] == 44
    assert all(assist.ADVISE in p and "<untrusted_thread>" in p for p in fake.prompts)
    assert sum("written by the owner" in p for p in fake.prompts) == 12   # notes, owner-authored
    assert rep["cost"]["tokens_in"] == 44 * 1000 and rep["cost"]["cost_usd"] > 0


def test_attacker_text_in_a_draft_fails_the_floor():
    rep = eval_ask.run(Fake(leak=True), ROOT)
    assert not rep["pass"] and len(rep["floors"]["attacker text in a draft"]) == 32


def test_an_invented_phone_fails_the_floor_and_a_note_fact_does_not():
    rep = eval_ask.run(Fake(invent=True), ROOT)
    assert not rep["pass"] and len(rep["floors"]["invented link/amount/phone in a draft"]) == 44
    clean = eval_ask.run(Fake(), ROOT)
    a02 = next(r for r in clean["rows"] if r["id"] == "a02-salary-floor")
    assert a02["draft"] == "My floor is $210k base." and a02["invented"] == []


def test_cli_writes_a_report_and_exits_by_the_floors(tmp_path, monkeypatch):
    root = tmp_path / "evals"
    for sub in ("injection", "attribution"):
        (root / sub).mkdir(parents=True)
        for p in (ROOT / sub).glob("*.json"):
            (root / sub / p.name).write_text(p.read_text())
    monkeypatch.setattr(providers, "get_provider", lambda s: Fake())
    assert cli.main(["eval-ask", "--dir", str(root), "--limit", "3"]) == 0
    monkeypatch.setattr(providers, "get_provider", lambda s: Fake(invent=True))
    assert cli.main(["eval-ask", "--dir", str(root), "--limit", "3"]) == 1
    reps = sorted((root / "results").glob("ask-*.json"))
    verdicts = sorted(json.loads(p.read_text())["pass"] for p in reps)
    assert len(reps) == 2 and verdicts == [False, True]      # the second run did not overwrite
    assert cli.main(["eval-ask", "--provider", "openai"]) == 2
