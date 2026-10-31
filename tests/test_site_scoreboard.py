"""The About page's results table is generated from the eval reports: it must match them, so a
new eval run cannot leave stale numbers on the site."""
from __future__ import annotations

from pathlib import Path

import pytest

from frontdesk import evaluate

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "site" / "frontdesk.html"


def test_page_table_matches_the_latest_eval_reports():
    page = PAGE.read_text()
    a, b = page.index(evaluate.SITE_START), page.index(evaluate.SITE_END) + len(evaluate.SITE_END)
    want = evaluate.scoreboard_html(evaluate.latest_reports(ROOT / "evals"))
    assert page[a:b] == want, "run: frontdesk scoreboard --site docs/site/frontdesk.html"


@pytest.mark.parametrize("model,name", [("anthropic:claude-opus-5-5", "Claude Opus 5.5"),
                                        ("claude-sonnet-5", "Claude Sonnet 5"),
                                        ("claude-fable-5-1", "Claude Fable 5.1")])
def test_display_model(model, name):
    assert evaluate.display_model(model) == name


def _rep(model, cost, acc=(70, 74), inj=(32, 32), compromised=False):
    return {"model": model, "prompt_version": "v", "run_at": "2026-10-30T00:00:00Z", "errors": [],
            "triage": {"needs_you_to_ignore": 0, "needs_you_recall": [33, 33], "accuracy": list(acc),
                       "urgency_band_agreement": [60, 74]},
            "injection": {"pass": list(inj),
                          "failures": [["i9", "", "planted text in reply"]] if compromised else []},
            "unsupported_spans_in_replies": [],
            "cost": {"cost_usd": cost, "calls": 100, "p50_latency_ms": 1000}}


def test_pick_on_top_failures_in_plain_words_and_cost_bars_scaled():
    html = evaluate.scoreboard_html([_rep("claude-sonnet-5", 0.5, compromised=True),
                                     _rep("claude-opus-5-5", 1.0), _rep("claude-fable-5-1", 2.5)])
    rows = [ln for ln in html.splitlines() if ln.strip().startswith("<tr")]
    assert "Claude Opus 5.5" in rows[0] and 'class="pick"' in rows[0] and "(default)" in rows[0]
    assert "Claude Fable 5.1" in rows[1] and "Claude Sonnet 5" in rows[2]
    assert "Attacker text in a reply" in rows[2] and 'class="fail"' in rows[2]
    assert 'class="bar cost"><i style="width:100%"' in rows[1]          # the dearest model
    assert 'class="bar cost"><i style="width:40%"' in rows[0]           # $10 of $25 per 1k


def test_replace_needs_markers():
    with pytest.raises(ValueError):
        evaluate.replace_site_block("<p>no markers</p>", "x")
