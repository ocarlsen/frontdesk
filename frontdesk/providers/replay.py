"""ReplayProvider: answers triage from recorded outputs instead of a model. Used by demo mode so
FrontDesk runs end to end with no API key and no network. It still goes through the real
render_user/validate path, so the recorded answers are checked like live ones."""
from __future__ import annotations

import json
from pathlib import Path

from .base import Completion, ProviderError, Usage

_OPEN, _CLOSE = "<untrusted_thread>", "</untrusted_thread>"


def thread_id_from_prompt(user: str) -> str:
    """The Gmail thread id of the Item serialized inside <untrusted_thread> (id 'gmail:<tid>').
    render_user escapes '<' inside the JSON, so the first open and last close tags are ours."""
    start, end = user.find(_OPEN), user.rfind(_CLOSE)
    if start < 0 or end < start:
        raise ProviderError("replay: no <untrusted_thread> block in the prompt")
    try:
        item_id = json.loads(user[start + len(_OPEN):end])["id"]
    except (ValueError, KeyError, TypeError) as e:
        raise ProviderError(f"replay: unreadable thread JSON ({type(e).__name__})") from None
    source, _, native = item_id.partition(":")
    return native if source == "gmail" else item_id


class ReplayProvider:
    name = "replay"
    model = "recorded"

    def __init__(self, recordings: dict[str, dict] | Path | str):
        if not isinstance(recordings, dict):
            recordings = json.loads(Path(recordings).read_text())
        self.recordings = recordings

    def complete_json(self, system: str, user: str, schema: dict,
                      max_tokens: int = 2048) -> Completion:
        tid = thread_id_from_prompt(user)
        rec = self.recordings.get(tid)
        if rec is None:
            raise ProviderError(f"replay: no recorded triage for thread {tid}")
        return Completion(dict(rec), Usage(model_served=self.model))
