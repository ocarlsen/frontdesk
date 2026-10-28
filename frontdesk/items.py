"""Provider-neutral records. Every source (Gmail now, Slack later) normalizes into Item;
everything downstream (store, triage, UI) sees only these shapes, never a source's raw API JSON."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Message:
    sender: str            # display form, e.g. "Jane Doe <jane@example.com>"
    sent_at: str           # ISO 8601 UTC
    body: str              # cleaned plain text, quoted history stripped where possible
    is_mine: bool = False  # sent by the account owner
    html: str = ""         # the HTML part, for DISPLAY only; never sent to a model


@dataclass
class Item:
    """One conversation that may need the owner: a mail thread, a Slack thread or DM."""
    id: str                # "<source>:<native id>", e.g. "gmail:18c2f..."
    source: str            # "gmail" | "slack"
    account: str           # the mailbox or workspace it came from
    subject: str
    participants: list[str]
    messages: list[Message]  # oldest first
    updated_at: str        # ISO 8601 UTC of the newest message
    labels: list[str] = field(default_factory=list)
    url: str = ""          # deep link to open it in the source app

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Item:
        d = dict(d)
        d["messages"] = [Message(**m) for m in d["messages"]]
        return cls(**d)


BUCKETS = ("needs_you", "fyi", "ignore")


@dataclass
class Triage:
    """The model's read of one Item. proposed_reply is a SUGGESTION shown to the owner; nothing
    in Phase A sends it, and later phases only ever turn it into a draft the owner sends."""
    item_id: str
    bucket: str            # one of BUCKETS
    urgency: int           # 1 (whenever) .. 5 (today)
    reason: str            # one line: why it is in this bucket
    proposed_reply: str    # empty when no reply is warranted
    model: str             # provider:model that produced it
    triaged_at: str        # ISO 8601 UTC
    item_updated_at: str   # Item.updated_at it was computed from; stale when the thread moves
    # Provenance, so any decision can be inspected and replayed:
    prompt_version: str = ""
    model_served: str = ""     # the model that actually answered (fallbacks can differ)
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read: int = 0
    cache_write: int = 0
    latency_ms: int = 0
    cost_usd: float | None = None
    summary: str = ""          # model-written, from untrusted mail: display as plain text only
    # Set when the owner moved the thread to another bucket; `bucket` then holds the owner's
    # choice and this holds what the model said. Not stored in the triage table.
    model_bucket: str = ""
