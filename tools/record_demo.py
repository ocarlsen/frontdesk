"""Records the demo inbox's answers from a LIVE model, with usage, into frontdesk/demo_data/
triage.json, so `frontdesk demo` replays genuine model output and its Why panel shows the real
model, tokens and cost. Billed: one call per demo thread (20). Usage:

    .venv/bin/python tools/record_demo.py [--model claude-opus-5-5]
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime

from frontdesk import config, triage
from frontdesk.demo import DEMO_ACCOUNT, DEMO_DIR, load_threads, shift_dates
from frontdesk.gmail.normalize import thread_to_item
from frontdesk.providers import get_provider


class Recorder:
    """Wraps the live provider to keep each call's raw answer and usage, keyed by thread id."""

    def __init__(self, inner):
        self.inner, self.name, self.model = inner, inner.name, inner.model
        self.calls: dict[str, dict] = {}

    def complete_json(self, system, user, schema, max_tokens=2048):
        from frontdesk.providers.replay import thread_id_from_prompt
        res = self.inner.complete_json(system, user, schema, max_tokens)
        self.calls[thread_id_from_prompt(user)] = {**res.data, "_usage": asdict(res.usage)}
        return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model")
    args = ap.parse_args()
    s = config.settings()
    if args.model:
        s = {**s, "model": args.model}
    rec = Recorder(get_provider(s))
    threads = load_threads(DEMO_DIR)
    shift_dates(threads, datetime.now(UTC))
    for t in threads:
        triage.triage_item(rec, thread_to_item(t, DEMO_ACCOUNT))   # validates like production
    missing = {t["id"] for t in threads} - set(rec.calls)
    if missing:
        raise SystemExit(f"no answer for {sorted(missing)}; recording not written")
    (DEMO_DIR / "triage.json").write_text(json.dumps(rec.calls, indent=1, ensure_ascii=False)
                                          + "\n")
    total = sum(triage.cost_usd(c["_usage"]["model_served"], c["_usage"]["tokens_in"],
                                c["_usage"]["tokens_out"]) or 0 for c in rec.calls.values())
    print(f"recorded {len(rec.calls)} answers from {rec.model}, est. ${total:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
