"""Anthropic adapter. Structured outputs (output_config.format) for schema-valid JSON, and
server-side refusal fallbacks so a classifier false positive on one odd email reroutes instead of
failing the thread."""
from __future__ import annotations

import json
import time

import anthropic

from .base import Completion, ProviderError, ProviderRefusal, Usage

FALLBACK_BETA = "server-side-fallback-2026-07-01"


# No prompt caching: automatic caching marks the LAST block, which is the per-thread text, so
# every call paid the 1.25x cache-write premium and none ever read it back (the first eval run
# showed 0% hits). The shared system prompt alone is below the minimum cacheable size. Revisit
# when the shared prefix grows (e.g. a per-user profile block).


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, effort: str = "medium"):
        """effort is an Anthropic-specific knob; it arrives via settings['provider_options']."""
        self.model = model
        self.effort = effort
        self.client = anthropic.Anthropic(api_key=api_key)

    def complete_json(self, system: str, user: str, schema: dict,
                      max_tokens: int = 2048) -> Completion:
        t0 = time.monotonic()
        try:
            resp = self.client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": self.effort,
                               "format": {"type": "json_schema", "schema": schema}},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.APIStatusError as e:
            raise ProviderError(f"anthropic {e.status_code}: {type(e).__name__}") from e
        except anthropic.APIConnectionError as e:
            raise ProviderError("anthropic: connection error") from e
        if resp.stop_reason == "refusal":
            raise ProviderRefusal("anthropic: model declined")
        if resp.stop_reason == "max_tokens":
            raise ProviderError("anthropic: hit max_tokens before finishing")
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if text is None:
            raise ProviderError("anthropic: no text block in response")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ProviderError("anthropic: response was not valid JSON") from e
        u = resp.usage
        return Completion(data, Usage(
            tokens_in=u.input_tokens or 0, tokens_out=u.output_tokens or 0,
            cache_read=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write=getattr(u, "cache_creation_input_tokens", 0) or 0,
            latency_ms=int((time.monotonic() - t0) * 1000),
            model_served=getattr(resp, "model", "") or self.model))
