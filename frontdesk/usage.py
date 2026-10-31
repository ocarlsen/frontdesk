"""How a draft or a sent reply relates to what FrontDesk wrote, for the usage log. Only the
verdict is stored (proposed | ask_draft | edited | written), never the text."""
from __future__ import annotations

import re

from .items import Item
from .store import Store


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _signoff() -> str:
    try:
        from . import config
        return config.settings().get("reply_signoff", "") or ""
    except Exception:  # noqa: BLE001 - a missing or unreadable settings file means no sign-off
        return ""


def origin_of(store: Store, item: Item, body: str, signoff: str | None = None) -> str:
    """'proposed' when `body` is the triage's proposed reply (with or without the sign-off),
    'ask_draft' when it is a draft an Ask answer wrote, 'edited' when FrontDesk had written one
    but this differs, 'written' when FrontDesk had written nothing for this thread."""
    from .assist import with_signoff
    sign = _signoff() if signoff is None else signoff
    text = _norm(body)
    tri = store.triage_for(item.id)
    proposal = tri.proposed_reply if tri else ""
    if proposal:
        forms = {_norm(proposal)}
        if item.source == "gmail":
            forms.add(_norm(with_signoff(proposal, sign)))
        if text in forms:
            return "proposed"
    drafts = [h.get("draft_reply", "") for h in store.ask_history(item.id)
              if h["role"] == "assistant" and h.get("draft_reply")]
    if any(_norm(d) == text for d in drafts):
        return "ask_draft"
    return "edited" if (proposal or drafts) else "written"
