"""Triage traces: one JSON line per ranking call (the exact input the model saw, its raw output
and the parsed result), for reading real traces before changing the prompt.

The file holds mail text, so it gets the same care as frontdesk.db: created 0600, never loosened,
local only. Append-only; when an append would pass TRACES_MAX_BYTES the file moves to
traces.1.jsonl (replacing any older one) and a fresh file starts. Appends hold a file lock,
since Sync, Keep and the CLI can run at once. Evals and the smoke check never write."""
from __future__ import annotations

import fcntl
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from . import config


def path() -> Path:
    return config.HOME / config.TRACES_FILE


def lock_path() -> Path:
    return path().with_suffix(".lock")


def rotated_path() -> Path:
    return path().with_name(path().stem + ".1" + path().suffix)


def enabled(settings: dict) -> bool:
    """The triage_traces setting; anything but a bool raises, naming the key and value."""
    v = settings.get("triage_traces", config.DEFAULTS["triage_traces"])
    if not isinstance(v, bool):
        raise ValueError(f"setting triage_traces must be true or false, got {v!r}")
    return v


def _tighten(p: Path) -> None:
    """Drop any group/other access (or exec bit) an existing file has picked up."""
    if p.exists() and p.stat().st_mode & 0o177:
        os.chmod(p, 0o600)


def append(rec: dict, max_bytes: int | None = None) -> None:
    """Append one record as one line, rotating first if it would pass the cap."""
    max_bytes = config.TRACES_MAX_BYTES if max_bytes is None else max_bytes
    # backslashreplace: a lone surrogate in mail text must not raise after the ranking is saved.
    line = (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8", "backslashreplace")
    p = path()
    config.ensure_home()
    lock = os.open(lock_path(), os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _tighten(p)
        size = p.stat().st_size if p.exists() else 0
        if size > 0 and size + len(line) > max_bytes:
            os.replace(p, rotated_path())
            _tighten(rotated_path())
            size = 0
        fd = os.open(p, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            if size and not _ends_with_newline(p):   # a torn tail must not swallow this record
                line = b"\n" + line
            os.write(fd, line)
        finally:
            os.close(fd)
    finally:
        os.close(lock)   # closing drops the flock


def _ends_with_newline(p: Path) -> bool:
    with open(p, "rb") as f:
        f.seek(-1, os.SEEK_END)
        return f.read(1) == b"\n"


def record(item, provider, version: str, trace: dict, outcome: str, triage=None,
           error: str = "") -> dict:
    """One trace row. `trace` is what triage_item filled (system, user, raw); `triage` is the
    saved Triage on success. Refusals and errors keep whatever was known when they happened."""
    t = triage
    return {
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "item_id": item.id,
        "prompt_version": version,
        "model_requested": f"{provider.name}:{provider.model}",
        "model_served": t.model_served if t else "",
        "system": trace.get("system", ""),
        "user": trace.get("user", ""),
        "raw": trace.get("raw", ""),
        "parsed": {"bucket": t.bucket, "urgency": t.urgency, "reason": t.reason,
                   "proposed_reply": t.proposed_reply, "summary": t.summary} if t else None,
        "tokens_in": t.tokens_in if t else None,
        "tokens_out": t.tokens_out if t else None,
        "cache_read": t.cache_read if t else None,
        "cache_write": t.cache_write if t else None,
        "latency_ms": t.latency_ms if t else None,
        "cost_usd": t.cost_usd if t else None,
        "outcome": outcome,
        "error": error,
    }


def _read(p: Path):
    """Records newest first, skipping a torn or unreadable line."""
    if not p.exists():
        return
    # Split on b"\n" only: str.splitlines() also breaks on U+2028, U+2029 and U+0085, which
    # json.dumps(ensure_ascii=False) leaves raw inside a string.
    for line in reversed(p.read_bytes().split(b"\n")):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:   # includes UnicodeDecodeError from a line torn mid-codepoint
            continue
        if isinstance(r, dict):
            yield r


def load(n: int, bucket: str | None = None, version: str | None = None) -> list[dict]:
    """The newest `n` records matching the filters, newest first; reads traces.1.jsonl only if
    the current file has too few."""
    out: list[dict] = []
    for p in (path(), rotated_path()):
        for r in _read(p):
            if bucket and (r.get("parsed") or {}).get("bucket") != bucket:
                continue
            if version and r.get("prompt_version") != version:
                continue
            out.append(r)
            if len(out) >= n:
                return out
    return out


def format_record(r: dict, system: bool = False) -> str:
    """One trace for a pager: header, INPUT (the system prompt only on request), RAW OUTPUT."""
    p = r.get("parsed") or {}
    what = f"{p.get('bucket', '?')}/{p.get('urgency', '?')}" if p else "-"
    head = (f"{r.get('ts', '?')}  {r.get('item_id', '?')}  {r.get('model_requested', '?')}  "
            f"{what}  {r.get('outcome', '?')}  prompt {r.get('prompt_version', '?')}")
    parts = ["=" * 78, head]
    if r.get("error"):
        parts.append(f"error: {r['error']}")
    if system:
        parts += ["--- SYSTEM " + "-" * 67, r.get("system", "")]
    parts += ["--- INPUT " + "-" * 68, r.get("user", ""),
              "--- RAW OUTPUT " + "-" * 63, r.get("raw") or "(none)"]
    return "\n".join(parts)
