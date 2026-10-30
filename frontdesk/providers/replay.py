"""ReplayProvider: answers triage from recorded outputs instead of a model. Used by demo mode so
FrontDesk runs end to end with no API key and no network. It still goes through the real
render_user/validate path, so the recorded answers are checked like live ones.

Recordings are keyed by item id ("gmail:<tid>", "slack:<channel>:<ts|dm>"). The first demo
recordings were keyed by the bare Gmail thread id; those still match their gmail: item."""
from __future__ import annotations

import json
from pathlib import Path

from .base import Completion, ProviderError, Usage

_OPEN, _CLOSE = "<untrusted_thread>", "</untrusted_thread>"


def item_id_from_prompt(user: str) -> str:
    """The id of the Item serialized inside <untrusted_thread>. render_user escapes '<' inside
    the JSON, so the first open and last close tags are ours."""
    start, end = user.find(_OPEN), user.rfind(_CLOSE)
    if start < 0 or end < start:
        raise ProviderError("replay: no <untrusted_thread> block in the prompt")
    try:
        item_id = json.loads(user[start + len(_OPEN):end])["id"]
    except (ValueError, KeyError, TypeError) as e:
        raise ProviderError(f"replay: unreadable thread JSON ({type(e).__name__})") from None
    if not isinstance(item_id, str):
        raise ProviderError("replay: thread id is not a string")
    return item_id


def thread_id_from_prompt(user: str) -> str:
    """The legacy key: the bare Gmail thread id for a Gmail item, the item id otherwise."""
    item_id = item_id_from_prompt(user)
    source, _, native = item_id.partition(":")
    return native if source == "gmail" else item_id


class ReplayProvider:
    name = "replay"
    model = "recorded"

    def __init__(self, recordings: dict[str, dict] | Path | str,
                 aliases: dict[str, str] | None = None):
        """aliases: {item id as loaded: id it was recorded under}, for ids that change between
        loads (the demo shifts Slack timestamps, which are part of a channel thread's id)."""
        if not isinstance(recordings, dict):
            recordings = json.loads(Path(recordings).read_text())
        self.recordings = recordings
        self.aliases = aliases or {}

    def key_for(self, item_id: str) -> str | None:
        """The recording key for an item: its (aliased) item id, else the legacy bare Gmail
        thread id; None when there is no recording."""
        key = self.aliases.get(item_id, item_id)
        if key in self.recordings:
            return key
        source, _, native = key.partition(":")
        if source == "gmail" and native in self.recordings:
            return native
        return None

    def complete_json(self, system: str, user: str, schema: dict,
                      max_tokens: int = 2048) -> Completion:
        item_id = item_id_from_prompt(user)
        key = self.key_for(item_id)
        if key is None:
            raise ProviderError(f"replay: no recorded triage for thread {item_id}")
        rec = dict(self.recordings[key])
        u = rec.pop("_usage", None)   # present when recorded from a live model
        if u is None:
            return Completion(rec, Usage(model_served=self.model))
        return Completion(rec, Usage(**u))
