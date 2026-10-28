"""Anthropic adapter. Structured outputs (output_config.format) for schema-valid JSON, automatic
prompt caching on the stable system prompt, and server-side refusal fallbacks so a classifier
false positive on one odd email reroutes instead of failing the thread."""
from __future__ import annotations

import json

import anthropic

from .base import ProviderError, ProviderRefusal

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, effort: str = "medium"):
        """effort is an Anthropic-specific knob; it arrives via settings['provider_options']."""
        self.model = model
        self.effort = effort
        self.client = anthropic.Anthropic(api_key=api_key)

    def complete_json(self, system: str, user: str, schema: dict, max_tokens: int = 2048) -> dict:
        try:
            resp = self.client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                cache_control={"type": "ephemeral"},
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
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ProviderError("anthropic: response was not valid JSON") from e
