"""OpenAI adapter. Responses API with Structured Outputs (text.format json_schema, strict), so the
model can only emit schema-valid JSON. `store=False`: mail content is not kept server-side for
later retrieval. The SDK is imported lazily so FrontDesk runs without it installed.

Verified against the installed `openai` SDK (resources/responses/responses.py create(),
types/responses/response_format_text_json_schema_config_param.py, response_usage.py,
response_output_refusal.py) and the Structured Outputs guide
(developers.openai.com/api/docs/guides/structured-outputs)."""
from __future__ import annotations

import copy
import json
import time

from .base import Completion, ProviderError, ProviderRefusal, Usage

FORMAT_NAME = "frontdesk_output"


def strict_schema(schema: dict) -> dict:
    """A copy of `schema` that meets strict mode: every object lists every property in
    `required` and sets additionalProperties false. A property the caller left optional becomes
    nullable instead (strict mode's way to say optional), so its meaning is kept."""
    out = copy.deepcopy(schema)
    _strictify(out)
    return out


def _strictify(node) -> None:
    if isinstance(node, list):
        for n in node:
            _strictify(n)
        return
    if not isinstance(node, dict):
        return
    if node.get("type") == "object" or "properties" in node:
        props = node.setdefault("properties", {})
        was_required = set(node.get("required", []))
        for key, sub in props.items():
            if key not in was_required and isinstance(sub, dict) and "type" in sub:
                t = sub["type"]
                types = t if isinstance(t, list) else [t]
                if "null" not in types:
                    sub["type"] = [*types, "null"]
                    if "enum" in sub and None not in sub["enum"]:
                        sub["enum"] = [*sub["enum"], None]
        node["required"] = list(props)
        node["additionalProperties"] = False
    for key in ("properties", "$defs", "definitions"):
        if isinstance(node.get(key), dict):
            for sub in node[key].values():
                _strictify(sub)
    for key in ("items", "anyOf", "allOf", "prefixItems"):
        if key in node:
            _strictify(node[key])


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str, effort: str | None = None):
        """effort maps to reasoning.effort for reasoning models; None leaves the model default
        (and sends nothing, so non-reasoning models accept the call)."""
        try:
            import openai
        except ImportError as e:  # pragma: no cover - exercised only without the extra
            raise ProviderError("openai provider needs: pip install 'frontdesk[openai]'") from e
        self._sdk = openai
        self.model = model
        self.effort = effort
        self.client = openai.OpenAI(api_key=api_key)

    def __repr__(self) -> str:
        return f"OpenAIProvider(model={self.model!r}, effort={self.effort!r})"

    __str__ = __repr__

    def request_kwargs(self, system: str, user: str, schema: dict, max_tokens: int) -> dict:
        kw = {
            "model": self.model,
            "instructions": system,
            "input": user,
            "max_output_tokens": max_tokens,
            "store": False,
            "text": {"format": {"type": "json_schema", "name": FORMAT_NAME,
                                "schema": strict_schema(schema), "strict": True}},
        }
        if self.effort:
            kw["reasoning"] = {"effort": self.effort}
        return kw

    def complete_json(self, system: str, user: str, schema: dict,
                      max_tokens: int = 2048) -> Completion:
        sdk = self._sdk
        t0 = time.monotonic()
        try:
            resp = self.client.responses.create(
                **self.request_kwargs(system, user, schema, max_tokens))
        except sdk.APIStatusError as e:
            raise ProviderError(f"openai {e.status_code}: {type(e).__name__}") from e
        except sdk.APIConnectionError as e:
            raise ProviderError("openai: connection error") from e
        except sdk.APIError as e:  # e.g. response validation; never echo the body
            raise ProviderError(f"openai: {type(e).__name__}") from e

        for item in resp.output or []:
            if getattr(item, "type", None) != "message":
                continue
            for part in item.content or []:
                if getattr(part, "type", None) == "refusal":
                    raise ProviderRefusal("openai: model declined")
        if resp.status == "incomplete":
            reason = getattr(resp.incomplete_details, "reason", None)
            if reason == "content_filter":
                raise ProviderRefusal("openai: blocked by content filter")
            if reason == "max_output_tokens":
                raise ProviderError("openai: hit max_output_tokens before finishing")
            raise ProviderError(f"openai: incomplete ({reason or 'unknown'})")
        if resp.status not in (None, "completed"):
            code = getattr(resp.error, "code", None) if resp.error else None
            raise ProviderError(f"openai: response {resp.status}" + (f" ({code})" if code else ""))
        text = resp.output_text
        if not text:
            raise ProviderError("openai: no output text in response")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ProviderError("openai: response was not valid JSON") from e
        if not isinstance(data, dict):
            raise ProviderError("openai: response JSON was not an object")

        u = resp.usage
        details = getattr(u, "input_tokens_details", None) if u else None
        cached = (getattr(details, "cached_tokens", 0) or 0) if details else 0
        total_in = (u.input_tokens or 0) if u else 0
        return Completion(data, Usage(
            # input_tokens includes the cached ones; Usage.tokens_in is the uncached remainder.
            tokens_in=max(total_in - cached, 0),
            tokens_out=(u.output_tokens or 0) if u else 0,   # includes reasoning tokens
            # cache_write stays 0: OpenAI reports input_tokens_details.cache_write_tokens, but
            # whether writes bill above the input rate is unverified, so they stay in tokens_in.
            cache_read=cached,
            latency_ms=int((time.monotonic() - t0) * 1000),
            model_served=getattr(resp, "model", "") or self.model))
