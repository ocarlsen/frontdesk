"""SQLite store: items (normalized source data), message HTML (display only, kept out of the item
rows so listing never loads it), triage (model output), triage failures (so a refusal or a broken
call is not re-billed on every sync), and an append-only action log that later phases write before
every side effect."""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from email.utils import parseaddr
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
    cost_usd REAL,
    summary TEXT NOT NULL DEFAULT ''
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
    -- 'archived': gone from the Gmail inbox; the next sync prunes it for good.
    -- 'done': handled, hidden in FrontDesk only, and shown again when a new message arrives
    --         (item_updated_at no longer matches).
    item_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    at TEXT NOT NULL,
    item_updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS notes (
    -- RETIRED: one note per address, before people. Copied into people/addresses once (see
    -- _migrate_people) and kept read-only for one release: triggers make every write raise.
    who TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT 'unrecorded'
);
CREATE TABLE IF NOT EXISTS people (
    -- A person the owner keeps a note on, reachable through any of their addresses. `name` is
    -- typed by the owner only (set_person_name refuses any other author); nothing copies a
    -- display name from mail into it, because display names are sender-controlled text and the
    -- notes block of Ask's prompt is trusted. `author` is the note's author (AUTHORS below).
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS addresses (
    -- Lowercase: a Gmail address, a Slack user key 'slack:<team_id>:<user_id>', or (kept as an
    -- alias for one release) a Slack display name from before user keys; see link_slack_names.
    addr TEXT PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES people(id)
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS asks (
    -- One Ask conversation per thread: the owner's questions and the model's answers.
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL,
    role TEXT NOT NULL,              -- 'owner' | 'assistant'
    text TEXT NOT NULL,
    extra TEXT NOT NULL DEFAULT '{}', -- assistant: {draft_reply, note_suggestions, model, cost}
    at TEXT NOT NULL,
    -- owner rows: who wrote the question; assistant rows: who asked for the answer
    author TEXT NOT NULL DEFAULT 'unrecorded'
);
CREATE TABLE IF NOT EXISTS situation (
    -- "What's going on": what is live for the owner right now, for Ask. Same authorship rule.
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    author TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
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
CREATE TABLE IF NOT EXISTS stars (
    -- "Starred in FrontDesk" for Slack threads only: Slack has no supported API for saving a
    -- message for later (stars.add has no user-visible effect since 2023). Gmail stars are
    -- Gmail's own STARRED label, read back on every sync.
    item_id TEXT PRIMARY KEY,
    at TEXT NOT NULL
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
    ("summary", "TEXT NOT NULL DEFAULT ''"),
]
# Columns added to owner-side memory tables, applied to older databases on open.
MEMORY_ADDED_COLUMNS = [("notes", "author", "TEXT NOT NULL DEFAULT 'unrecorded'"),
                        ("asks", "author", "TEXT NOT NULL DEFAULT 'unrecorded'")]
TRIAGE_FIELDS = ("item_id", "bucket", "urgency", "reason", "proposed_reply", "model",
                 "triaged_at", "item_updated_at", "prompt_version", "model_served", "tokens_in",
                 "tokens_out", "cache_read", "cache_write", "latency_ms", "cost_usd", "summary")


# Authorship of owner-side memory (notes, Ask questions, situation items):
#   'owner'          typed or clicked by the owner in the FrontDesk UI (a model suggestion the
#                    owner saved with a click counts as the owner's);
#   'session:<name>' a tool or agent session writing on the owner's behalf (the CLI);
#   'unrecorded'     rows from before authorship was recorded.
# Confirmed means author == 'owner'. This is a record for honest writers, NOT a security
# boundary: any local process can open this database, or call the local API, and claim any author.
OWNER = "owner"
UNRECORDED = "unrecorded"
_SESSION = re.compile(r"session:[a-z0-9._-]{1,40}")
SITUATION_MAX_ITEMS = 50
SITUATION_MAX_CHARS = 500
NOTE_MAX_CHARS = 2000
NAME_MAX_CHARS = 100
PEOPLE_MARKER = "people_migrated"
_TOMBSTONE = ("CREATE TRIGGER IF NOT EXISTS notes_retired_{op} BEFORE {op} ON notes BEGIN "
              "SELECT RAISE(ABORT, 'notes is retired: write to people and addresses'); END")


class InvalidMemory(ValueError):
    """A memory write with a bad author, text or id. The message is safe to show the owner."""


def check_author(author) -> str:
    """The author a writer may claim: 'owner' or 'session:<name>'. Never 'unrecorded', which
    only marks old rows, and never a default: a missing author is an error."""
    if author == OWNER or (isinstance(author, str) and _SESSION.fullmatch(author)):
        return author
    raise InvalidMemory("author must be 'owner' or 'session:<name>' "
                        "(name: a-z, 0-9, '.', '_', '-'; at most 40)")


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def owner_keys(item: Item) -> set[str]:
    """The owner's own keys on one item, lowercase: the mailbox (Gmail) or workspace host (Slack),
    plus the owner's participant keys. Gmail: the address of every message the owner sent. Slack:
    item.owner_key, the owner's user key from auth.test at sync, so the owner is excluded even
    from a thread they never posted in, and the owner's display name on that item (so an old
    note keyed on the owner's Slack name stays refused). A Slack item stored before user keys
    has no owner_key; for it, the senders of the owner's messages count, as they used to."""
    keys = {item.account.strip().lower()}
    if item.source == "gmail":
        for m in item.messages:
            if m.is_mine:
                addr = parseaddr(m.sender)[1].strip().lower()
                if "@" in addr:
                    keys.add(addr)
    elif item.owner_key:
        keys.add(item.owner_key.strip().lower())
        keys.add(item.names.get(item.owner_key, "").strip().lower())
    else:
        keys |= {m.sender.strip().lower() for m in item.messages if m.is_mine}
    keys.discard("")
    return keys


def is_slack_key(addr: str) -> bool:
    return addr.startswith("slack:")


def is_legacy_slack_name(addr: str) -> bool:
    """An address from before Slack user keys: a Slack display name (no '@', no 'slack:')."""
    return bool(addr) and "@" not in addr and not is_slack_key(addr)


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or config.DB_PATH
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._migrate()
        self._migrate_people()
        self.path.chmod(0o600)

    def _migrate(self) -> None:
        hcols = {r["name"] for r in self.db.execute("PRAGMA table_info(hidden)")}
        if "item_updated_at" not in hcols:
            try:
                with self.db:
                    self.db.execute("ALTER TABLE hidden ADD COLUMN item_updated_at "
                                    "TEXT NOT NULL DEFAULT ''")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e):
                    raise
        added = [("triage", n, d) for n, d in TRIAGE_ADDED_COLUMNS] + MEMORY_ADDED_COLUMNS
        for table, name, decl in added:
            cols = {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}
            if name in cols:
                continue
            try:
                with self.db:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
            except sqlite3.OperationalError as e:
                # Another process (the server, a CLI run) added it between our read and write.
                if "duplicate column" not in str(e):
                    raise

    def meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def _migrate_people(self) -> None:
        """One note per address (notes) -> one person per note, reachable by that address. Runs
        once per database: under BEGIN IMMEDIATE, so two processes opening the store together
        serialize here, and only while the marker is absent (checked again inside the lock). A
        row is copied only when its address has no person yet. A note keyed on one of the
        owner's own addresses is not copied, and is listed in the marker's report. Afterwards the
        notes table is read-only."""
        if self.meta(PEOPLE_MARKER) is not None:
            return
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.meta(PEOPLE_MARKER) is None:
                mine = self.all_owner_keys()
                copied, skipped = 0, []
                for r in self.db.execute("SELECT who, text, updated_at, author FROM notes "
                                         "ORDER BY updated_at, who").fetchall():
                    who = r["who"].strip().lower()
                    if not who or not r["text"].strip():
                        continue
                    if who in mine:
                        skipped.append(who)
                        continue
                    if self.db.execute("SELECT 1 FROM addresses WHERE addr=?",
                                       (who,)).fetchone():
                        continue
                    pid = self.db.execute(
                        "INSERT INTO people (name, note, author, created_at, updated_at) "
                        "VALUES ('',?,?,?,?)",
                        (r["text"], r["author"], r["updated_at"], r["updated_at"])).lastrowid
                    self.db.execute("INSERT INTO addresses VALUES (?,?)", (who, pid))
                    copied += 1
                for op in ("INSERT", "UPDATE", "DELETE"):
                    self.db.execute(_TOMBSTONE.format(op=op))
                self.db.execute("INSERT INTO meta VALUES (?,?)", (PEOPLE_MARKER, json.dumps(
                    {"at": now(), "copied": copied, "skipped_owner_address": skipped})))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

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
                                   ("stars", "item_id"), ("items", "id")):
                    db.execute(f"DELETE FROM {table} WHERE {col}=?", (item_id,))
        return len(stale)

    def set_labels(self, item_id: str, labels: list[str]) -> None:
        """Change only an item's labels (e.g. UNREAD), leaving its messages and HTML alone."""
        row = self.db.execute("SELECT data FROM items WHERE id=?", (item_id,)).fetchone()
        if row is None:
            return
        d = json.loads(row["data"])
        d["labels"] = labels
        with self.tx() as db:
            db.execute("UPDATE items SET data=? WHERE id=?", (json.dumps(d), item_id))

    # ---- people, Ask history and situation: owner-side memory, each row with its author
    def all_owner_keys(self) -> set[str]:
        """owner_keys() over every stored item: addresses that must never become a person."""
        out: set[str] = set()
        for r in self.db.execute("SELECT data FROM items"):
            out |= owner_keys(Item.from_dict(json.loads(r["data"])))
        return out

    def _addresses(self, person_id: int) -> list[str]:
        return [r["addr"] for r in self.db.execute(
            "SELECT addr FROM addresses WHERE person_id=? ORDER BY rowid", (person_id,))]

    def _person_dict(self, r: sqlite3.Row) -> dict:
        return {"id": r["id"], "name": r["name"], "note": r["note"], "author": r["author"],
                "created_at": r["created_at"], "updated_at": r["updated_at"],
                "addresses": self._addresses(r["id"])}

    def people_for(self, addrs: list[str]) -> list[dict]:
        """The people reachable through any of `addrs`, once each (two addresses of one person
        give one entry), in the order their first address appears. Each: {id, name, note,
        author, created_at, updated_at, addresses (all of theirs), matched (those in addrs)}."""
        keys = list(dict.fromkeys(a.strip().lower() for a in addrs if a and a.strip()))
        if not keys:
            return []
        rows = self.db.execute(
            f"SELECT a.addr, p.* FROM addresses a JOIN people p ON p.id = a.person_id "
            f"WHERE a.addr IN ({','.join('?' * len(keys))})", keys).fetchall()
        by_addr = {r["addr"]: r for r in rows}
        out: dict[int, dict] = {}
        for k in keys:
            r = by_addr.get(k)
            if r is None:
                continue
            if r["id"] not in out:
                out[r["id"]] = {**self._person_dict(r), "matched": []}
            out[r["id"]]["matched"].append(k)
        return list(out.values())

    def notes_for(self, people: list[str]) -> dict[str, dict]:
        """{address: {"text", "author", "updated_at"}} for each given address whose person has a
        note (the same shape as before people: a note is now reachable through any address)."""
        out = {}
        for p in self.people_for(people):
            if p["note"]:
                for k in p["matched"]:
                    out[k] = {"text": p["note"], "author": p["author"],
                              "updated_at": p["updated_at"]}
        return out

    @staticmethod
    def _note_text(text) -> str:
        if not isinstance(text, str) or len(text) > NOTE_MAX_CHARS:
            raise InvalidMemory(f"a note is text of at most {NOTE_MAX_CHARS} characters")
        if not text.strip():
            # Saving empty text used to delete the note, which let any writer erase one.
            raise InvalidMemory("a note needs text (to remove one, the owner uses Delete on "
                                "the Memory page)")
        return text.strip()

    @staticmethod
    def _owner_only(author, what: str) -> None:
        if check_author(author) != OWNER:
            raise InvalidMemory(f"only the owner can {what}")

    def _person(self, person_id) -> sqlite3.Row:
        if not isinstance(person_id, int) or isinstance(person_id, bool):
            raise InvalidMemory("expected a person id")
        row = self.db.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
        if row is None:
            raise InvalidMemory("no such person")
        return row

    @staticmethod
    def _replace_check(row: sqlite3.Row, author: str) -> None:
        if author != OWNER and row["author"] == OWNER:
            raise InvalidMemory("only the owner can replace a note the owner wrote; a session "
                                "can append to it")

    def save_note(self, who: str, text: str, author: str, append: bool = False) -> None:
        """Set the note on whoever owns address `who`, creating that person if none does. With
        `append`, add `text` to the existing note; the combined note counts as the owner's only
        if both parts are. Empty text is refused, never a delete; a session may add or append
        but not replace a note the owner wrote; the owner's own addresses are refused."""
        author = check_author(author)
        who = who.strip().lower() if isinstance(who, str) else ""
        if not who:
            raise InvalidMemory("a note needs a person")
        text = self._note_text(text)
        with self.tx() as db:
            if who in self.all_owner_keys():
                raise InvalidMemory("that is your own address: notes are about other people")
            row = db.execute("SELECT p.* FROM addresses a JOIN people p ON p.id = a.person_id "
                             "WHERE a.addr=?", (who,)).fetchone()
            if row is None:
                t = now()
                pid = db.execute("INSERT INTO people (name, note, author, created_at, updated_at) "
                                 "VALUES ('',?,?,?,?)", (text, author, t, t)).lastrowid
                db.execute("INSERT INTO addresses VALUES (?,?)", (who, pid))
                return
            if append and row["note"]:
                text = (row["note"] + "\n" + text)[:NOTE_MAX_CHARS]
                if row["author"] != OWNER:
                    author = row["author"]
            else:
                self._replace_check(row, author)
            db.execute("UPDATE people SET note=?, author=?, updated_at=? WHERE id=?",
                       (text, author, now(), row["id"]))

    def update_person(self, person_id: int, text: str, author: str,
                      name: str | None = None) -> None:
        """Replace a person's note (same rule as save_note) and, when `name` is given, set the
        name, which only the owner can do."""
        author = check_author(author)
        text = self._note_text(text)
        if name is not None:
            self._owner_only(author, "name a person")
        with self.tx() as db:
            row = self._person(person_id)
            if text != row["note"] or author != row["author"]:
                self._replace_check(row, author)
                db.execute("UPDATE people SET note=?, author=?, updated_at=? WHERE id=?",
                           (text, author, now(), person_id))
            if name is not None:
                self._set_name(person_id, name)

    def set_person_name(self, person_id: int, name: str, author: str) -> None:
        """The ONLY writer of people.name: owner-typed, one line, at most NAME_MAX_CHARS; empty
        clears it. Leaves the note's date alone (it dates the note in Ask's prompt)."""
        self._owner_only(author, "name a person")
        with self.tx():
            self._person(person_id)
            self._set_name(person_id, name)

    def _set_name(self, person_id: int, name) -> None:
        if not isinstance(name, str) or len(name.strip()) > NAME_MAX_CHARS \
                or "\n" in name or "\r" in name:
            raise InvalidMemory(f"a name is one line of at most {NAME_MAX_CHARS} characters")
        self.db.execute("UPDATE people SET name=? WHERE id=?", (name.strip(), person_id))

    def confirm_person(self, person_id: int, author: str) -> None:
        """The owner vouches for a note as written: author becomes 'owner'; text and date stay."""
        self._owner_only(author, "confirm")
        with self.tx() as db:
            self._person(person_id)
            db.execute("UPDATE people SET author=? WHERE id=?", (OWNER, person_id))

    def confirm_note(self, who: str, author: str) -> None:
        """confirm_person, for the person reached through address `who`."""
        self._owner_only(author, "confirm")
        p = self.people_for([who]) if isinstance(who, str) else []
        if not p:
            raise InvalidMemory("no note for that person")
        self.confirm_person(p[0]["id"], author)

    def delete_person(self, person_id: int, author: str) -> None:
        """Remove a person, their addresses and their note. Owner only."""
        self._owner_only(author, "delete a person")
        with self.tx() as db:
            self._person(person_id)
            db.execute("DELETE FROM addresses WHERE person_id=?", (person_id,))
            db.execute("DELETE FROM people WHERE id=?", (person_id,))

    def merge_people(self, person_id: int, into: int, author: str) -> None:
        """Move every address of `person_id` to `into` and append its note to theirs; then
        `person_id` is gone. Owner only. Authorship: the merged note counts as the owner's only
        if both notes were the owner's (as with append); otherwise it keeps the unconfirmed
        author, `into`'s first. The name stays `into`'s, or takes the other's when `into` has
        none. Refused, rather than cut, when the joined note would be too long."""
        self._owner_only(author, "merge people")
        with self.tx() as db:
            src, dst = self._person(person_id), self._person(into)
            if src["id"] == dst["id"]:
                raise InvalidMemory("a person cannot be merged into themselves")
            note = "\n".join(n for n in (dst["note"], src["note"]) if n)
            if len(note) > NOTE_MAX_CHARS:
                raise InvalidMemory(f"the merged note would pass {NOTE_MAX_CHARS} characters; "
                                    "shorten one first")
            authors = [a for a, n in ((dst["author"], dst["note"]), (src["author"], src["note"]))
                       if n]
            merged_author = next((a for a in authors if a != OWNER), OWNER if authors
                                 else dst["author"])
            db.execute("UPDATE addresses SET person_id=? WHERE person_id=?", (into, person_id))
            db.execute("UPDATE people SET note=?, author=?, name=?, created_at=?, updated_at=? "
                       "WHERE id=?", (note, merged_author, dst["name"] or src["name"],
                                      min(dst["created_at"], src["created_at"]), now(), into))
            db.execute("DELETE FROM people WHERE id=?", (person_id,))

    def people_all(self) -> list[dict]:
        """Everyone remembered, most recently changed first."""
        return [self._person_dict(r) for r in self.db.execute(
            "SELECT * FROM people ORDER BY updated_at DESC, id DESC")]

    def slack_names(self) -> dict[str, str]:
        """{Slack key: the display name its newest stored item shows}: other-party-controlled
        text, for the page only (Memory, the notes boxes). Never sent to a model."""
        out: dict[str, tuple[str, str]] = {}
        for r in self.db.execute("SELECT updated_at, data FROM items WHERE source='slack'"):
            for k, name in (json.loads(r["data"]).get("names") or {}).items():
                k = k.strip().lower()
                if name and r["updated_at"] >= out.get(k, ("", ""))[0]:
                    out[k] = (r["updated_at"], name)
        return {k: n for k, (_, n) in out.items()}

    def link_slack_names(self) -> dict:
        """Old Slack notes were keyed by display name. For each such address (is_legacy_slack_name)
        whose name belongs to exactly ONE Slack user across every stored Slack item, that user's
        key is added to the same person; the old name stays as an alias for one release, so
        nothing that still holds it breaks. Left alone: names seen for two or more users
        (ambiguous), names not seen at all, a name that is the owner's, and a key that already
        belongs to someone else (joining two people is a merge, which only the owner does).

        Idempotent per address rather than run-once behind a marker, since a name first seen in a
        later sync should still link: an address already linked is a no-op. Runs under BEGIN
        IMMEDIATE, so two processes linking at once serialize and the second finds the work done;
        INSERT OR IGNORE backs that up. Returns {"linked": {name: key}, "ambiguous": [name]}."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            users: dict[str, set[str]] = {}
            mine: set[str] = set()
            for r in self.db.execute("SELECT data FROM items WHERE source='slack'").fetchall():
                item = Item.from_dict(json.loads(r["data"]))
                mine |= owner_keys(item)
                for k, name in item.names.items():
                    k = k.strip().lower()
                    if is_slack_key(k) and ":bot:" not in k and name.strip():
                        users.setdefault(name.strip().lower(), set()).add(k)
            linked, ambiguous = {}, []
            legacy = [r for r in self.db.execute("SELECT addr, person_id FROM addresses "
                                                 "ORDER BY rowid").fetchall()
                      if is_legacy_slack_name(r["addr"])]
            for r in legacy:
                keys = users.get(r["addr"], set())
                if len(keys) > 1:
                    ambiguous.append(r["addr"])
                if len(keys) != 1:
                    continue
                key = next(iter(keys))
                if key in mine or r["addr"] in mine:
                    continue
                held = self.db.execute("SELECT person_id FROM addresses WHERE addr=?",
                                       (key,)).fetchone()
                if held is not None:
                    continue          # already linked (re-run), or someone else's: leave it
                self.db.execute("INSERT OR IGNORE INTO addresses VALUES (?,?)",
                                (key, r["person_id"]))
                linked[r["addr"]] = key
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return {"linked": linked, "ambiguous": ambiguous}

    def mail_names(self) -> dict[str, str]:
        """{address: the display name its newest Gmail message used}: sender-controlled text, for
        the Memory page to show greyed as "from mail, unconfirmed". Never sent to a model."""
        out: dict[str, tuple[str, str]] = {}
        for r in self.db.execute("SELECT data FROM items WHERE source='gmail'"):
            for m in json.loads(r["data"])["messages"]:
                name, addr = parseaddr(m["sender"])
                addr = addr.strip().lower()
                if name.strip() and "@" in addr and m["sent_at"] >= out.get(addr, ("", ""))[0]:
                    out[addr] = (m["sent_at"], name.strip())
        return {a: n for a, (_, n) in out.items()}

    def ask_history(self, item_id: str) -> list[dict]:
        return [{"role": r["role"], "text": r["text"], "author": r["author"], "at": r["at"],
                 **json.loads(r["extra"])}
                for r in self.db.execute("SELECT * FROM asks WHERE item_id=? ORDER BY id",
                                         (item_id,))]

    def add_ask(self, item_id: str, role: str, text: str, author: str,
                extra: dict | None = None) -> None:
        author = check_author(author)
        with self.tx() as db:
            db.execute("INSERT INTO asks (item_id, role, text, extra, at, author) "
                       "VALUES (?,?,?,?,?,?)",
                       (item_id, role, text, json.dumps(extra or {}), now(), author))

    def situation(self) -> list[dict]:
        """Oldest first: {"id", "text", "author", "created_at", "updated_at"}."""
        return [dict(r) for r in self.db.execute(
            "SELECT id, text, author, created_at, updated_at FROM situation ORDER BY id")]

    @staticmethod
    def _situation_text(text) -> str:
        if not isinstance(text, str) or not text.strip():
            raise InvalidMemory("a situation item needs text")
        if len(text.strip()) > SITUATION_MAX_CHARS:
            raise InvalidMemory(f"a situation item is at most {SITUATION_MAX_CHARS} characters")
        return text.strip()

    def add_situation(self, text: str, author: str) -> int:
        author, text = check_author(author), self._situation_text(text)
        with self.tx() as db:
            n = db.execute("SELECT COUNT(*) FROM situation").fetchone()[0]
            if n >= SITUATION_MAX_ITEMS:
                raise InvalidMemory(f"What's going on holds at most {SITUATION_MAX_ITEMS} items; "
                                    "delete one first")
            t = now()
            return db.execute("INSERT INTO situation (text, author, created_at, updated_at) "
                              "VALUES (?,?,?,?)", (text, author, t, t)).lastrowid

    def _situation_write(self, sql: str, args: tuple) -> None:
        with self.tx() as db:
            if db.execute(sql, args).rowcount == 0:
                raise InvalidMemory("no such situation item")

    def update_situation(self, item_id: int, text: str, author: str) -> None:
        author, text = check_author(author), self._situation_text(text)
        self._situation_write("UPDATE situation SET text=?, author=?, updated_at=? WHERE id=?",
                              (text, author, now(), item_id))

    def confirm_situation(self, item_id: int) -> None:
        """Author becomes 'owner'; text and dates stay."""
        self._situation_write("UPDATE situation SET author=? WHERE id=?", (OWNER, item_id))

    def delete_situation(self, item_id: int) -> None:
        self._situation_write("DELETE FROM situation WHERE id=?", (item_id,))

    def related(self, item: Item, limit: int = 5) -> list[tuple[Item, str]]:
        """Other stored threads (including archived or done ones) that share a participant other
        than the owner with `item`, newest first, each with its triage summary if any."""
        mine = {p.lower() for p in item.participants} - owner_keys(item)
        out = []
        for r in self.db.execute("SELECT i.data, t.summary FROM items i LEFT JOIN triage t "
                                 "ON t.item_id = i.id WHERE i.id != ?", (item.id,)):
            other = Item.from_dict(json.loads(r["data"]))
            theirs = {p.lower() for p in other.participants} - owner_keys(other)
            if mine & theirs:
                out.append((other, r["summary"] or ""))
        out.sort(key=lambda it: it[0].updated_at, reverse=True)
        return out[:limit]

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

    def hide(self, item_id: str, reason: str, item_updated_at: str = "") -> None:
        with self.tx() as db:
            db.execute("INSERT OR REPLACE INTO hidden (item_id, reason, at, item_updated_at) "
                       "VALUES (?,?,?,?)", (item_id, reason, now(), item_updated_at))

    def is_hidden(self, item_id: str) -> bool:
        """Hidden right now: archived, or done and nothing new has arrived since."""
        return self.db.execute(
            "SELECT 1 FROM hidden h JOIN items i ON i.id = h.item_id WHERE h.item_id=? AND "
            "(h.reason='archived' OR h.item_updated_at = i.updated_at)",
            (item_id,)).fetchone() is not None

    def unhide(self, item_id: str) -> None:
        with self.tx() as db:
            db.execute("DELETE FROM hidden WHERE item_id=?", (item_id,))

    def hidden_reason(self, item_id: str) -> str:
        """'archived' or 'done' while that hides the item now, else ''."""
        r = self.db.execute(
            "SELECT h.reason FROM hidden h JOIN items i ON i.id = h.item_id WHERE h.item_id=? "
            "AND (h.reason='archived' OR h.item_updated_at = i.updated_at)",
            (item_id,)).fetchone()
        return r["reason"] if r else ""

    # ---- stars: Gmail's STARRED label for Gmail threads, a local flag for Slack threads
    def is_starred(self, item: Item) -> bool:
        if item.source == "gmail":
            return "STARRED" in item.labels
        return self.db.execute("SELECT 1 FROM stars WHERE item_id=?",
                               (item.id,)).fetchone() is not None

    def set_local_star(self, item_id: str, starred: bool) -> None:
        with self.tx() as db:
            if starred:
                db.execute("INSERT OR IGNORE INTO stars VALUES (?,?)", (item_id, now()))
            else:
                db.execute("DELETE FROM stars WHERE item_id=?", (item_id,))

    def archived_ids(self, source: str) -> set[str]:
        """Items of this source that FrontDesk archived and still holds."""
        return {r["item_id"] for r in self.db.execute(
            "SELECT h.item_id FROM hidden h JOIN items i ON i.id = h.item_id "
            "WHERE h.reason='archived' AND i.source=?", (source,))}

    def failure_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM triage_failures").fetchone()[0]

    def ranked(self, hidden: bool = False) -> list[tuple[Item, Triage | None]]:
        """Every item with its triage, ranked: needs_you, then fyi, then ignore, then untriaged;
        within a bucket by urgency then recency. hidden=True ranks the items that archive or
        done hide right now instead (the Starred view still shows starred ones)."""
        rows = self.db.execute(
            "SELECT i.data, t.*, l.owner_bucket FROM items i "
            "LEFT JOIN triage t ON t.item_id = i.id "
            "LEFT JOIN labels l ON l.item_id = i.id AND l.item_updated_at = i.updated_at "
            "WHERE " + ("" if hidden else "NOT ") + "EXISTS (SELECT 1 FROM hidden h WHERE "
            "  h.item_id = i.id AND (h.reason = 'archived' OR h.item_updated_at = i.updated_at)) "
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
