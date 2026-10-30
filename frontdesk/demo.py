"""Demo mode: a synthetic inbox for alex@example.com, normalized by the real Gmail and Slack code
paths and triaged by the real triage loop with recorded model answers. No Google account, no
Slack token, no API key, no network. Fixtures live in frontdesk/demo_data/: threads/ (raw
threads.get?format=full JSON), slack/ (raw Slack Web API JSON: auth.test, users.info,
conversations.list entries, history and replies) and triage.json (the recorded answers)."""
from __future__ import annotations

import copy
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import triage
from .gmail.normalize import thread_to_item
from .providers.replay import ReplayProvider
from .slack.sync import sync as slack_sync
from .store import Store

DEMO_ACCOUNT = "alex@example.com"
DEMO_DIR = Path(__file__).resolve().parent / "demo_data"
NEWEST_AGE = timedelta(minutes=10)


def load_threads(demo_dir: Path = DEMO_DIR) -> list[dict]:
    files = sorted((demo_dir / "threads").glob("*.json"))
    if not files:
        raise FileNotFoundError(f"no demo fixtures in {demo_dir / 'threads'}")
    return [json.loads(f.read_text()) for f in files]


def load_slack(demo_dir: Path = DEMO_DIR) -> dict | None:
    """{"auth_test", "users", "conversations": [{"channel", "history", "replies"}]}, or None when
    the demo has no Slack fixtures."""
    sdir = demo_dir / "slack"
    if not (sdir / "workspace.json").exists():
        return None
    ws = json.loads((sdir / "workspace.json").read_text())
    ws["conversations"] = [json.loads(f.read_text())
                           for f in sorted((sdir / "conversations").glob("*.json"))]
    return ws


class FixtureSlackClient:
    """Answers the read calls slack.sync makes (the SlackClient interface) from the fixtures.
    Writes refuse: nothing in the demo reaches Slack. history() ignores `oldest`, since the
    fixtures are already the window and the demo's clock is shifted, not the real one."""

    def __init__(self, workspace: dict):
        self.ws = workspace
        self._convs = {c["channel"]["id"]: c for c in workspace["conversations"]}

    def auth_test(self) -> dict:
        return dict(self.ws["auth_test"])

    def list_conversations(self) -> list[dict]:
        return [copy.deepcopy(c["channel"]) for c in self.ws["conversations"]]

    def history(self, channel: str, oldest_ts: str) -> list[dict]:
        return copy.deepcopy(self._convs[channel]["history"])

    def replies(self, channel: str, thread_ts: str) -> list[dict]:
        return copy.deepcopy(self._convs[channel]["replies"][thread_ts])

    def info(self, channel: str) -> dict:
        return copy.deepcopy(self._convs[channel]["channel"])

    def user(self, user_id: str) -> dict:
        return copy.deepcopy(self.ws["users"][user_id])

    def post_message(self, *a, **k):
        raise RuntimeError("demo: nothing is posted to Slack")

    def mark(self, *a, **k):
        raise RuntimeError("demo: nothing is marked in Slack")


def _slack_ts_fields(ws: dict):
    """Yield (dict, key) for every Slack timestamp in the fixtures."""
    for c in ws["conversations"]:
        if "last_read" in c["channel"]:
            yield c["channel"], "last_read"
        msgs = list(c["history"]) + [m for thread in c["replies"].values() for m in thread]
        for m in msgs:
            for k in ("ts", "thread_ts", "latest_reply"):
                if k in m:
                    yield m, k


def _ts_us(ts: str) -> int:
    sec, _, frac = ts.partition(".")
    return int(sec) * 1_000_000 + int((frac + "000000")[:6])


def _us_ts(us: int) -> str:
    return f"{us // 1_000_000}.{us % 1_000_000:06d}"


def shift_dates(threads: list[dict], now: datetime, slack: dict | None = None) -> dict[str, str]:
    """Re-base every internalDate and Slack ts (in place) so the newest message of either source
    lands NEWEST_AGE before now, keeping the gaps between messages, so the demo always reads as a
    fresh inbox. Returns {shifted Slack ts: fixture ts}: a channel thread's item id carries its
    root ts, so this is how a shifted id maps back to the id its recording is keyed by."""
    newest = max(int(m["internalDate"]) for t in threads for m in t["messages"])
    if slack:
        newest = max([newest, *(_ts_us(m["ts"]) // 1000 for c in slack["conversations"]
                                for m in c["history"])])
    delta = int((now - NEWEST_AGE).timestamp() * 1000) - newest
    for t in threads:
        for m in t["messages"]:
            m["internalDate"] = str(int(m["internalDate"]) + delta)
    ts_map: dict[str, str] = {}
    if slack:
        for c in slack["conversations"]:
            c["replies"] = {_us_ts(_ts_us(k) + delta * 1000): v for k, v in c["replies"].items()}
        for d, k in _slack_ts_fields(slack):
            new = _us_ts(_ts_us(d[k]) + delta * 1000)
            ts_map[new] = d[k]
            d[k] = new
    return ts_map


def recording_key(item_id: str, ts_map: dict[str, str]) -> str:
    """The id an item's recording is stored under: its item id as the fixtures are written
    (Slack channel thread ids carry the unshifted root ts; DM and Gmail ids never shift)."""
    source, _, rest = item_id.partition(":")
    if source == "slack":
        channel, _, ts = rest.partition(":")
        if ts in ts_map:
            return f"slack:{channel}:{ts_map[ts]}"
    return item_id


def load_items(store: Store, now: datetime | None = None, demo_dir: Path = DEMO_DIR,
               log=lambda *_: None) -> dict[str, str]:
    """Normalize every fixture into `store` (Gmail through thread_to_item, Slack through the
    real slack.sync over FixtureSlackClient). Returns {item id: recording key}."""
    threads = load_threads(demo_dir)
    slack = load_slack(demo_dir)
    ts_map = shift_dates(threads, now or datetime.now(UTC), slack)
    keys: dict[str, str] = {}
    for t in threads:
        item = thread_to_item(t, DEMO_ACCOUNT)
        if item is not None:
            store.upsert_item(item)
            keys[item.id] = item.id
    if slack:
        slack_sync(store, {"slack_days": 7, "slack_max_items": 60}, token="demo", log=log,
                   client=FixtureSlackClient(slack))
        for r in store.db.execute("SELECT id FROM items WHERE source='slack'"):
            keys[r["id"]] = recording_key(r["id"], ts_map)
    return keys


def load_demo(store: Store, now: datetime | None = None, demo_dir: Path = DEMO_DIR,
              log=lambda *_: None, warn=None) -> int:
    """Fill `store` with the demo inbox and its triage. Returns how many items were loaded.
    A thread with no recording yet is left untriaged (the page shows it under Not triaged yet)
    and named in one `warn` line (stderr by default)."""
    keys = load_items(store, now, demo_dir, log)
    replay = ReplayProvider(demo_dir / "triage.json", aliases=keys)
    missing = sorted(k for i, k in keys.items() if replay.key_for(i) is None)
    if missing:
        (warn or (lambda s: print(s, file=sys.stderr)))(
            f"demo: no recorded triage for {len(missing)} thread(s), shown as Not triaged yet: "
            f"{', '.join(missing)} (record them with tools/record_demo.py --only-missing)")
    triage.run(store, replay, log=log)
    return len(keys)
