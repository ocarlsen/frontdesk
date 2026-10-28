"""SQLite store: items (normalized source data), message HTML (display only, kept out of the item
rows so listing never loads it), triage (model output), triage failures (so a refusal or a broken
call is not re-billed on every sync), and an append-only action log that later phases write before
every side effect."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from . import config
from .items import Item, Triage

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS message_html (
    item_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    html TEXT NOT NULL,
    PRIMARY KEY (item_id, idx)
);
CREATE TABLE IF NOT EXISTS triage (
    item_id TEXT PRIMARY KEY REFERENCES items(id),
    bucket TEXT NOT NULL,
    urgency INTEGER NOT NULL,
    reason TEXT NOT NULL,
    proposed_reply TEXT NOT NULL,
    model TEXT NOT NULL,
    triaged_at TEXT NOT NULL,
    item_updated_at TEXT NOT NULL,
    prompt_version TEXT NOT NULL DEFAULT '',
    model_served TEXT NOT NULL DEFAULT '',
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    cache_read INTEGER NOT NULL DEFAULT 0,
    cache_write INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL
);
CREATE TABLE IF NOT EXISTS triage_failures (
    item_id TEXT PRIMARY KEY,
    item_updated_at TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    kind TEXT NOT NULL,          -- 'refusal' (terminal) | 'error' (retried up to MAX_ATTEMPTS)
    attempts INTEGER NOT NULL,
    last_error TEXT NOT NULL,
    last_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hidden (
    item_id TEXT PRIMARY KEY,    -- archived from FrontDesk; the next sync prunes it for good
    reason TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS labels (
    -- The owner's correction of a ranking: private ground truth for `frontdesk eval --mine`.
    item_id TEXT NOT NULL,
    item_updated_at TEXT NOT NULL,   -- a new message makes the old correction stale
    owner_bucket TEXT NOT NULL,
    model_bucket TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    at TEXT NOT NULL,
    PRIMARY KEY (item_id, item_updated_at)
);
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idem_key TEXT UNIQUE NOT NULL,
    item_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

MAX_ATTEMPTS = 3
# Columns added after the first release, applied to older databases on open.
TRIAGE_ADDED_COLUMNS = [
    ("prompt_version", "TEXT NOT NULL DEFAULT ''"),
    ("model_served", "TEXT NOT NULL DEFAULT ''"),
    ("tokens_in", "INTEGER NOT NULL DEFAULT 0"),
    ("tokens_out", "INTEGER NOT NULL DEFAULT 0"),
    ("cache_read", "INTEGER NOT NULL DEFAULT 0"),
    ("cache_write", "INTEGER NOT NULL DEFAULT 0"),
    ("latency_ms", "INTEGER NOT NULL DEFAULT 0"),
    ("cost_usd", "REAL"),
]
TRIAGE_FIELDS = ("item_id", "bucket", "urgency", "reason", "proposed_reply", "model",
                 "triaged_at", "item_updated_at", "prompt_version", "model_served", "tokens_in",
                 "tokens_out", "cache_read", "cache_write", "latency_ms", "cost_usd")


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or config.DB_PATH
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._migrate()
        self.path.chmod(0o600)

    def _migrate(self) -> None:
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(triage)")}
        with self.db:
            for name, decl in TRIAGE_ADDED_COLUMNS:
                if name not in cols:
                    self.db.execute(f"ALTER TABLE triage ADD COLUMN {name} {decl}")

    @contextmanager
    def tx(self):
        with self.db:
            yield self.db

    def upsert_item(self, item: Item) -> None:
        html = [m.html for m in item.messages]
        bare = replace(item, messages=[replace(m, html="") for m in item.messages])
        with self.tx() as db:
            db.execute(
                "INSERT INTO items(id, source, updated_at, data) VALUES (?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at, data=excluded.data",
                (item.id, item.source, item.updated_at, json.dumps(bare.to_dict())),
            )
            db.execute("DELETE FROM message_html WHERE item_id=?", (item.id,))
            db.executemany("INSERT INTO message_html VALUES (?,?,?)",
                           [(item.id, i, h) for i, h in enumerate(html) if h])

    def prune(self, source: str, account: str, keep_ids: set[str]) -> int:
        """Drop this source+account's items (and their triage) that a complete sync no longer
        lists, e.g. threads archived since. Returns how many were removed."""
        stale = [r["id"] for r in self.db.execute(
            "SELECT id, data FROM items WHERE source=?", (source,))
            if r["id"] not in keep_ids and json.loads(r["data"])["account"] == account]
        with self.tx() as db:
            for item_id in stale:
                for table, col in (("triage", "item_id"), ("triage_failures", "item_id"),
                                   ("message_html", "item_id"), ("hidden", "item_id"),
                                   ("items", "id")):
                    db.execute(f"DELETE FROM {table} WHERE {col}=?", (item_id,))
        return len(stale)

    def get_item(self, item_id: str) -> Item | None:
        """The item WITHOUT message HTML; use message_html() for display."""
        row = self.db.execute("SELECT data FROM items WHERE id=?", (item_id,)).fetchone()
        return Item.from_dict(json.loads(row["data"])) if row else None

    def message_html(self, item_id: str, idx: int) -> str | None:
        row = self.db.execute("SELECT html FROM message_html WHERE item_id=? AND idx=?",
                              (item_id, idx)).fetchone()
        return row["html"] if row else None

    def html_indexes(self) -> dict[str, set[int]]:
        out: dict[str, set[int]] = {}
        for r in self.db.execute("SELECT item_id, idx FROM message_html"):
            out.setdefault(r["item_id"], set()).add(r["idx"])
        return out

    def items_needing_triage(self, prompt_version: str = "") -> list[Item]:
        """Items never triaged, whose thread moved, or triaged under another prompt version;
        minus those whose failure for this exact (thread state, prompt) is terminal or has used
        up its retries. A refusal is never re-billed; an error is retried MAX_ATTEMPTS times."""
        rows = self.db.execute(
            "SELECT i.data FROM items i "
            "LEFT JOIN triage t ON t.item_id = i.id "
            "LEFT JOIN triage_failures f ON f.item_id = i.id "
            "  AND f.item_updated_at = i.updated_at AND f.prompt_version = ? "
            "WHERE (t.item_id IS NULL OR t.item_updated_at != i.updated_at "
            "       OR t.prompt_version != ?) "
            "  AND (f.item_id IS NULL OR (f.kind = 'error' AND f.attempts < ?)) "
            "ORDER BY i.updated_at DESC",
            (prompt_version, prompt_version, MAX_ATTEMPTS),
        ).fetchall()
        return [Item.from_dict(json.loads(r["data"])) for r in rows]

    def save_triage(self, t: Triage) -> None:
        with self.tx() as db:
            db.execute(
                f"INSERT OR REPLACE INTO triage ({','.join(TRIAGE_FIELDS)}) "
                f"VALUES ({','.join('?' * len(TRIAGE_FIELDS))})",
                tuple(getattr(t, f) for f in TRIAGE_FIELDS),
            )
            db.execute("DELETE FROM triage_failures WHERE item_id=?", (t.item_id,))

    def record_failure(self, item: Item, prompt_version: str, kind: str, error: str) -> None:
        """Count attempts per (item state, prompt version); a new message or prompt resets it."""
        with self.tx() as db:
            row = db.execute("SELECT item_updated_at, prompt_version, attempts FROM "
                             "triage_failures WHERE item_id=?", (item.id,)).fetchone()
            same = row and row["item_updated_at"] == item.updated_at \
                and row["prompt_version"] == prompt_version
            attempts = row["attempts"] + 1 if same else 1
            db.execute("INSERT OR REPLACE INTO triage_failures VALUES (?,?,?,?,?,?,?)",
                       (item.id, item.updated_at, prompt_version, kind, attempts,
                        error[:300], now()))

    # ---- actions: written BEFORE the side effect, so a crash or a double-click leaves a record
    def action(self, idem_key: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM actions WHERE idem_key=?", (idem_key,)).fetchone()

    def begin_action(self, idem_key: str, item_id: str, kind: str, payload: dict) -> int:
        """Insert a pending action; the UNIQUE idem_key makes a concurrent duplicate fail here."""
        with self.tx() as db:
            cur = db.execute("INSERT INTO actions (idem_key, item_id, kind, payload, status, "
                             "created_at) VALUES (?,?,?,?,?,?)",
                             (idem_key, item_id, kind, json.dumps(payload), "pending", now()))
            return cur.lastrowid

    def finish_action(self, action_id: int, status: str, result: dict | None = None) -> None:
        with self.tx() as db:
            if result is None:
                db.execute("UPDATE actions SET status=? WHERE id=?", (status, action_id))
            else:
                db.execute("UPDATE actions SET status=?, payload=? WHERE id=?",
                           (status, json.dumps(result), action_id))

    def set_label(self, item: Item, owner_bucket: str) -> None:
        t = self.db.execute("SELECT bucket, model, prompt_version FROM triage WHERE item_id=?",
                            (item.id,)).fetchone()
        with self.tx() as db:
            db.execute("INSERT OR REPLACE INTO labels VALUES (?,?,?,?,?,?,?)",
                       (item.id, item.updated_at, owner_bucket, t["bucket"] if t else "",
                        t["model"] if t else "", t["prompt_version"] if t else "", now()))

    def labels(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM labels").fetchall()

    def hide(self, item_id: str, reason: str) -> None:
        with self.tx() as db:
            db.execute("INSERT OR REPLACE INTO hidden VALUES (?,?,?)", (item_id, reason, now()))

    def is_hidden(self, item_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM hidden WHERE item_id=?",
                               (item_id,)).fetchone() is not None

    def unhide(self, item_id: str) -> None:
        with self.tx() as db:
            db.execute("DELETE FROM hidden WHERE item_id=?", (item_id,))

    def failure_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM triage_failures").fetchone()[0]

    def ranked(self) -> list[tuple[Item, Triage | None]]:
        """Every item with its triage, ranked: needs_you, then fyi, then ignore, then untriaged;
        within a bucket by urgency then recency."""
        rows = self.db.execute(
            "SELECT i.data, t.*, l.owner_bucket FROM items i "
            "LEFT JOIN triage t ON t.item_id = i.id "
            "LEFT JOIN labels l ON l.item_id = i.id AND l.item_updated_at = i.updated_at "
            "WHERE i.id NOT IN (SELECT item_id FROM hidden) "
            "ORDER BY CASE COALESCE(l.owner_bucket, t.bucket) WHEN 'needs_you' THEN 0 "
            "WHEN 'fyi' THEN 1 WHEN 'ignore' THEN 2 ELSE 3 END, t.urgency DESC, "
            "i.updated_at DESC"
        ).fetchall()
        out = []
        for r in rows:
            item = Item.from_dict(json.loads(r["data"]))
            tri = None
            if r["bucket"] is not None:
                tri = Triage(**{f: r[f] for f in TRIAGE_FIELDS})
                if r["owner_bucket"] and r["owner_bucket"] != tri.bucket:
                    tri.model_bucket, tri.bucket = tri.bucket, r["owner_bucket"]
            out.append((item, tri))
        return out
