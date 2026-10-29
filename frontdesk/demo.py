"""Demo mode: a synthetic inbox for alex@example.com, normalized by the real Gmail code path and
triaged by the real triage loop with recorded model answers. No Google account, no API key, no
network. Fixtures live in fixtures/demo/ (raw threads.get?format=full JSON plus triage.json)."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import triage
from .gmail.normalize import thread_to_item
from .providers.replay import ReplayProvider
from .store import Store

DEMO_ACCOUNT = "alex@example.com"
DEMO_DIR = Path(__file__).resolve().parent / "demo_data"
NEWEST_AGE = timedelta(minutes=10)


def load_threads(demo_dir: Path = DEMO_DIR) -> list[dict]:
    files = sorted((demo_dir / "threads").glob("*.json"))
    if not files:
        raise FileNotFoundError(f"no demo fixtures in {demo_dir / 'threads'}")
    return [json.loads(f.read_text()) for f in files]


def shift_dates(threads: list[dict], now: datetime) -> None:
    """Re-base every internalDate (in place) so the newest message lands NEWEST_AGE before now,
    keeping the gaps between messages, so the demo always reads as a fresh inbox."""
    newest = max(int(m["internalDate"]) for t in threads for m in t["messages"])
    delta = int((now - NEWEST_AGE).timestamp() * 1000) - newest
    for t in threads:
        for m in t["messages"]:
            m["internalDate"] = str(int(m["internalDate"]) + delta)


def load_demo(store: Store, now: datetime | None = None, demo_dir: Path = DEMO_DIR,
              log=lambda *_: None) -> int:
    """Fill `store` with the demo inbox and its triage. Returns how many items were loaded."""
    threads = load_threads(demo_dir)
    shift_dates(threads, now or datetime.now(UTC))
    count = 0
    for t in threads:
        item = thread_to_item(t, DEMO_ACCOUNT)
        if item is not None:
            store.upsert_item(item)
            count += 1
    triage.run(store, ReplayProvider(demo_dir / "triage.json"), log=log)
    return count
