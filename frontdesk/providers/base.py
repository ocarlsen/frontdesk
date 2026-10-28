"""The one seam between FrontDesk and any model vendor. Triage (and later the agent loop) talks
only to Provider; swapping vendors is a settings change, not a code change. Keep it small: every
method added here is a method every adapter must implement and parity-test."""
from __future__ import annotations

from typing import Protocol


class ProviderError(Exception):
    """A call failed in a way the caller should record and move past (not crash the run)."""


class ProviderRefusal(ProviderError):
    """The model declined. Recorded as a failed triage, never retried in a loop."""


class Provider(Protocol):
    name: str    # "anthropic", "openai", ...
    model: str

    def complete_json(self, system: str, user: str, schema: dict, max_tokens: int = 2048) -> dict:
        """One turn constrained to `schema` (JSON Schema, additionalProperties false). `system` must
        be stable across calls so providers that cache prefixes can; put volatile text in `user`."""
        ...
