"""Records the demo inbox's answers from a LIVE model, with usage, into frontdesk/demo_data/
triage.json, so `frontdesk demo` replays genuine model output and its Why panel shows the real
model, tokens and cost. Billed: one call per demo thread recorded. It prints the planned call
count before calling; --dry-run stops there. Usage:

    .venv/bin/python tools/record_demo.py [--model claude-opus-5-5] [--only-missing] [--dry-run]

--only-missing records just the threads with no recording yet and keeps every existing entry
exactly as it is (new entries are appended under their item id).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from frontdesk import triage
from frontdesk.demo import DEMO_DIR, load_items
from frontdesk.providers.replay import ReplayProvider, item_id_from_prompt
from frontdesk.store import Store


class Recorder:
    """Wraps the live provider to keep each call's raw answer and usage, keyed by the item's
    recording key (its item id as the fixtures are written)."""

    def __init__(self, inner, keys: dict[str, str]):
        self.inner, self.name, self.model = inner, inner.name, inner.model
        self.keys = keys
        self.calls: dict[str, dict] = {}

    def complete_json(self, system, user, schema, max_tokens=2048):
        res = self.inner.complete_json(system, user, schema, max_tokens)
        item_id = item_id_from_prompt(user)
        self.calls[self.keys.get(item_id, item_id)] = {**res.data,
                                                       "_usage": asdict(res.usage)}
        return res


def main(argv: list[str] | None = None, provider=None, demo_dir: Path = DEMO_DIR,
         now: datetime | None = None, out=print) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model")
    ap.add_argument("--only-missing", action="store_true",
                    help="record only threads with no recording; keep the rest unchanged")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, call nothing")
    args = ap.parse_args(argv)
    path = demo_dir / "triage.json"
    existing = json.loads(path.read_text()) if path.exists() else {}
    with tempfile.TemporaryDirectory(prefix="frontdesk-record-") as tmp:
        store = Store(Path(tmp) / "demo.db")
        keys = load_items(store, now or datetime.now(UTC), demo_dir)
        replay = ReplayProvider(existing, aliases=keys)
        todo = [store.get_item(i) for i in sorted(keys, key=keys.get)
                if not args.only_missing or replay.key_for(i) is None]
        store.db.close()
    out(f"planned: {len(todo)} live model call(s) for {len(keys)} demo threads"
        + (" (only missing)" if args.only_missing else ""))
    for it in todo:
        out(f"  {keys[it.id]}")
    if args.dry_run or not todo:
        return 0
    if provider is None:
        from frontdesk import config
        from frontdesk.providers import get_provider
        s = config.settings()
        if args.model:
            s = {**s, "model": args.model}
        provider = get_provider(s)
    rec = Recorder(provider, keys)
    for it in todo:
        triage.triage_item(rec, it)   # validates like production
    missing = {keys[it.id] for it in todo} - set(rec.calls)
    if missing:
        raise SystemExit(f"no answer for {sorted(missing)}; recording not written")
    result = {**existing, **rec.calls} if args.only_missing else rec.calls
    path.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    total = sum(triage.cost_usd(c["_usage"]["model_served"], c["_usage"]["tokens_in"],
                                c["_usage"]["tokens_out"]) or 0 for c in rec.calls.values())
    out(f"recorded {len(rec.calls)} answers from {rec.model}, est. ${total:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
