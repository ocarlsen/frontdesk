"""Google Gemini adapter (Gemini Developer API, API key). JSON output constrained by
`response_json_schema` with response_mime_type application/json; the system prompt goes in
`system_instruction`, apart from the user text. The SDK is imported lazily so FrontDesk runs
without it installed.

Verified against the installed `google-genai` SDK (types.GenerateContentConfig field docs,
types.FinishReason, types.BlockedReason, types.GenerateContentResponseUsageMetadata, errors.py)
and ai.google.dev/gemini-api/docs/structured-output and /thinking."""
from __future__ import annotations

import contextlib
import copy
import json
import time

from .base import Completion, ProviderError, ProviderRefusal, Usage

# The JSON Schema keywords response_json_schema accepts (GenerateContentConfig docstring).
SUPPORTED_KEYWORDS = frozenset({
    "$id", "$defs", "$ref", "$anchor", "type", "format", "title", "description", "enum",
    "items", "prefixItems", "minItems", "maxItems", "minimum", "maximum", "anyOf", "oneOf",
    "properties", "additionalProperties", "required", "propertyOrdering"})
# Keywords whose value is a map of name -> subschema rather than a schema itself.
_SCHEMA_MAPS = ("properties", "$defs")
_SCHEMA_LISTS = ("anyOf", "oneOf", "prefixItems")

# Finish/block reasons that mean the model or a safety filter declined, not a transient failure.
REFUSAL_FINISH = frozenset({"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION",
                            "IMAGE_SAFETY", "IMAGE_PROHIBITED_CONTENT", "IMAGE_RECITATION"})


def gemini_schema(schema: dict) -> dict:
    """A copy of `schema` holding only keywords response_json_schema supports (FrontDesk's
    schemas already fit; this drops e.g. "$schema" or "pattern" rather than risk a 400)."""
    if not isinstance(schema, dict):
        return schema
    out = {}
    for key, val in schema.items():
        if key not in SUPPORTED_KEYWORDS:
            continue
        if key in _SCHEMA_MAPS and isinstance(val, dict):
            out[key] = {k: gemini_schema(v) for k, v in val.items()}
        elif key in _SCHEMA_LISTS and isinstance(val, list):
            out[key] = [gemini_schema(v) for v in val]
        elif key in ("items", "additionalProperties") and isinstance(val, dict):
            out[key] = gemini_schema(val)
        else:
            out[key] = copy.deepcopy(val)
    return out


def _transport_errors() -> tuple[type[BaseException], ...]:
    """Connection/timeout errors surface from the HTTP library, not google.genai.errors."""
    errs: list[type[BaseException]] = []
    for mod in ("httpx", "httpx2"):
        with contextlib.suppress(ImportError, AttributeError):
            errs.append(__import__(mod).TransportError)
    return tuple(errs)


def _enum_name(v) -> str:
    return getattr(v, "value", None) or str(v or "")


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, thinking_level: str | None = None):
        """thinking_level is passed to ThinkingConfig when set; None keeps the model default."""
        try:
            from google import genai
            from google.genai import errors, types
        except ImportError as e:  # pragma: no cover - exercised only without the extra
            raise ProviderError("gemini provider needs: pip install 'frontdesk[gemini]'") from e
        self._errors, self._types = errors, types
        self.model = model
        self.thinking_level = thinking_level
        self.client = genai.Client(api_key=api_key, vertexai=False)

    def __repr__(self) -> str:
        return f"GeminiProvider(model={self.model!r}, thinking_level={self.thinking_level!r})"

    __str__ = __repr__

    def config(self, system: str, schema: dict, max_tokens: int):
        kw = {"system_instruction": system, "max_output_tokens": max_tokens,
              "response_mime_type": "application/json",
              "response_json_schema": gemini_schema(schema)}
        if self.thinking_level:
            kw["thinking_config"] = self._types.ThinkingConfig(thinking_level=self.thinking_level)
        return self._types.GenerateContentConfig(**kw)

    def complete_json(self, system: str, user: str, schema: dict,
                      max_tokens: int = 2048) -> Completion:
        t0 = time.monotonic()
        try:
            resp = self.client.models.generate_content(
                model=self.model, contents=user, config=self.config(system, schema, max_tokens))
        except self._errors.APIError as e:  # str(e) embeds the response body: never use it
            raise ProviderError(f"gemini {e.code}: {e.status or type(e).__name__}") from e
        except _transport_errors() as e:
            raise ProviderError("gemini: connection error") from e

        fb = resp.prompt_feedback
        if fb is not None and fb.block_reason:
            raise ProviderRefusal(f"gemini: prompt blocked ({_enum_name(fb.block_reason)})")
        if not resp.candidates:
            raise ProviderError("gemini: no candidates in response")
        cand = resp.candidates[0]
        finish = _enum_name(cand.finish_reason)
        if finish in REFUSAL_FINISH:
            raise ProviderRefusal(f"gemini: blocked ({finish})")
        if finish == "MAX_TOKENS":
            raise ProviderError("gemini: hit max_output_tokens before finishing")
        if finish and finish not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
            raise ProviderError(f"gemini: stopped early ({finish})")
        parts = (cand.content.parts if cand.content else None) or []
        text = "".join(p.text for p in parts if p.text and not p.thought)
        if not text:
            raise ProviderError("gemini: no text in response")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ProviderError("gemini: response was not valid JSON") from e
        if not isinstance(data, dict):
            raise ProviderError("gemini: response JSON was not an object")

        u = resp.usage_metadata
        prompt = (u.prompt_token_count or 0) if u else 0
        cached = (u.cached_content_token_count or 0) if u else 0
        out = ((u.candidates_token_count or 0) + (u.thoughts_token_count or 0)) if u else 0
        return Completion(data, Usage(
            # prompt_token_count includes cached content; tokens_in is the uncached remainder.
            tokens_in=max(prompt - cached, 0),
            # Thinking bills as output ("response pricing is the sum of output tokens and
            # thinking tokens", Gemini thinking docs).
            tokens_out=out, cache_read=cached,
            latency_ms=int((time.monotonic() - t0) * 1000),
            model_served=resp.model_version or self.model))
