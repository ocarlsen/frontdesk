"""The "Try to hijack it" gallery: built from the real suite and recordings, every planted quote
exact, every case recorded for every model, and exported with the demo."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from frontdesk import gallery
from frontdesk.export import _export_gallery

EVALS = Path(__file__).resolve().parents[1] / "evals"


def test_every_attack_is_in_the_gallery_once_with_every_model():
    d = gallery.build(EVALS)
    ids = [c["id"] for g in d["groups"] for c in g["cases"]]
    suite = sorted(p.stem for p in (EVALS / "injection").glob("*.json"))
    assert sorted(ids) == suite and len(ids) == len(set(ids)) == 32
    keys = [m["key"] for m in d["models"]]
    assert keys == list(gallery.MODEL_ORDER)
    for g in d["groups"]:
        for c in g["cases"]:
            assert set(c["results"]) == set(keys), c["id"]
            assert c["planted"], c["id"]


def test_recordings_match_the_current_prompt():
    from frontdesk import triage
    d = gallery.build(EVALS)
    assert {m["prompt_version"] for m in d["models"]} == {triage.PROMPT_VERSION}


def test_a_planted_quote_that_is_not_in_the_email_is_refused(tmp_path):
    root = tmp_path / "evals"
    (root / "injection").mkdir(parents=True)
    case = json.loads((EVALS / "injection" / "i01-direct-receipt-escalate.json").read_text())
    (root / "injection" / "i01-direct-receipt-escalate.json").write_text(json.dumps(case))
    (root / "hijack-gallery.json").write_text(json.dumps({"groups": [{
        "key": "x", "title": "X", "about": "", "cases": [
            {"id": "i01-direct-receipt-escalate", "planted": ["not in the email"]}]}]}))
    with pytest.raises(ValueError, match="planted quote not found"):
        gallery.build(root)


def test_export_writes_the_page_with_its_csp_and_data(tmp_path):
    (tmp_path / "api").mkdir()
    assert _export_gallery(tmp_path, EVALS)
    page = (tmp_path / "hijack.html").read_text()
    assert 'http-equiv="Content-Security-Policy"' in page and "script-src 'self'" in page
    assert (tmp_path / "hijack.js").exists() and (tmp_path / "hijack.css").exists()
    data = json.loads((tmp_path / "api" / "hijack.json").read_text())
    assert len(data["groups"]) == 10


def test_export_skips_the_gallery_without_the_suite(tmp_path):
    (tmp_path / "api").mkdir()
    assert _export_gallery(tmp_path, tmp_path / "no-evals") is False
