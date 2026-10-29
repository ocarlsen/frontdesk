"""OpenAI and Gemini adapters against fake SDK clients: no network, no key. Responses are built
with the SDKs' own response models from recorded-shaped dicts, so a field the adapter reads that
the SDK does not have fails here."""
from __future__ import annotations

import copy
import json

import pytest

from frontdesk import assist, triage
from frontdesk.providers import ProviderError, ProviderRefusal

openai = pytest.importorskip("openai")
genai_types = pytest.importorskip("google.genai.types")
genai_errors = pytest.importorskip("google.genai.errors")
httpx2 = pytest.importorskip("httpx2")

from frontdesk.providers.gemini_provider import (  # noqa: E402
    SUPPORTED_KEYWORDS,
    GeminiProvider,
    gemini_schema,
)
from frontdesk.providers.openai_provider import OpenAIProvider, strict_schema  # noqa: E402

KEY = "sk-TESTKEY-must-never-leak-0123456789"
BODY_SECRET = "Dear Alice, the wire code is 4417"   # stands in for a response/error body
ANSWER = {"bucket": "fyi", "urgency": 2, "reason": "r", "proposed_reply": "", "summary": "s"}
SCHEMAS = [pytest.param(triage.SCHEMA, id="triage"), pytest.param(assist.SCHEMA, id="assist")]


class Recorder:
    """Stands in for client.responses / client.models: records kwargs, returns or raises."""

    def __init__(self, result):
        self.result, self.calls = result, []

    def __call__(self, **kw):
        self.calls.append(kw)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


# ---------- OpenAI ----------

def oa_response(content=None, status="completed", incomplete=None, cached=40):
    from openai.types.responses import Response
    content = content if content is not None else [
        {"type": "output_text", "text": json.dumps(ANSWER), "annotations": []}]
    return Response.model_validate({
        "id": "resp_1", "object": "response", "created_at": 1, "model": "gpt-test-2026-01-01",
        "status": status, "incomplete_details": incomplete,
        "output": [{"type": "message", "id": "msg_1", "role": "assistant",
                    "status": "completed" if status == "completed" else "incomplete",
                    "content": content}],
        "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
        "usage": {"input_tokens": 1000, "input_tokens_details": {"cached_tokens": cached,
                                                                 "cache_write_tokens": 0},
                  "output_tokens": 120, "output_tokens_details": {"reasoning_tokens": 20},
                  "total_tokens": 1120}})


def oa(result, **opts):
    p = OpenAIProvider(KEY, "gpt-test", **opts)
    rec = Recorder(result)
    p.client.responses.create = rec
    return p, rec


def _req():
    return httpx2.Request("POST", "https://api.openai.com/v1/responses")


def test_openai_normal_answer_and_usage():
    p, rec = oa(oa_response())
    c = p.complete_json("SYS", "USER", triage.SCHEMA, max_tokens=900)
    assert c.data == ANSWER
    u = c.usage
    assert (u.tokens_in, u.tokens_out, u.cache_read, u.cache_write) == (960, 120, 40, 0)
    assert u.model_served == "gpt-test-2026-01-01"
    assert u.latency_ms >= 0
    kw = rec.calls[0]
    assert kw["model"] == "gpt-test" and kw["instructions"] == "SYS" and kw["input"] == "USER"
    assert kw["max_output_tokens"] == 900 and kw["store"] is False
    fmt = kw["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True and fmt["name"]
    assert "reasoning" not in kw


def test_openai_effort_option_sent():
    p, rec = oa(oa_response(), effort="low")
    p.complete_json("s", "u", triage.SCHEMA)
    assert rec.calls[0]["reasoning"] == {"effort": "low"}


def test_openai_refusal():
    p, _ = oa(oa_response(content=[{"type": "refusal", "refusal": "I can't help with that."}]))
    with pytest.raises(ProviderRefusal):
        p.complete_json("s", "u", triage.SCHEMA)


def test_openai_content_filter_is_refusal():
    p, _ = oa(oa_response(status="incomplete", incomplete={"reason": "content_filter"},
                          content=[]))
    with pytest.raises(ProviderRefusal):
        p.complete_json("s", "u", triage.SCHEMA)


def test_openai_truncation():
    partial = [{"type": "output_text", "text": '{"bucket": "fy', "annotations": []}]
    p, _ = oa(oa_response(status="incomplete", incomplete={"reason": "max_output_tokens"},
                          content=partial))
    with pytest.raises(ProviderError, match="max_output_tokens") as ei:
        p.complete_json("s", "u", triage.SCHEMA)
    assert not isinstance(ei.value, ProviderRefusal)


@pytest.mark.parametrize("exc, expect", [
    (lambda: openai.RateLimitError(BODY_SECRET, response=httpx2.Response(429, request=_req()),
                                   body={"error": {"message": BODY_SECRET}}),
     "openai 429: RateLimitError"),
    (lambda: openai.InternalServerError(BODY_SECRET, body={"error": {"message": BODY_SECRET}},
                                        response=httpx2.Response(500, request=_req())),
     "openai 500: InternalServerError"),
    (lambda: openai.APIConnectionError(request=_req()), "openai: connection error"),
    (lambda: openai.APITimeoutError(request=_req()), "openai: connection error"),
])
def test_openai_api_errors_carry_status_not_body(exc, expect):
    p, _ = oa(exc())
    with pytest.raises(ProviderError) as ei:
        p.complete_json("s", "u", triage.SCHEMA)
    assert str(ei.value) == expect
    assert BODY_SECRET not in str(ei.value) and not isinstance(ei.value, ProviderRefusal)


@pytest.mark.parametrize("text", ["not json {", "[1, 2]"])
def test_openai_invalid_json(text):
    p, _ = oa(oa_response(content=[{"type": "output_text", "text": text, "annotations": []}]))
    with pytest.raises(ProviderError, match="JSON"):
        p.complete_json("s", "u", triage.SCHEMA)


# ---------- Gemini ----------

def gm_response(text=None, finish="STOP", block=None, cached=300):
    d = {"modelVersion": "gemini-test-001",
         "usageMetadata": {"promptTokenCount": 1000, "cachedContentTokenCount": cached,
                           "candidatesTokenCount": 100, "thoughtsTokenCount": 50,
                           "totalTokenCount": 1150}}
    if block:
        d["promptFeedback"] = {"blockReason": block}
    else:
        parts = [{"text": "thinking about it", "thought": True},
                 {"text": json.dumps(ANSWER) if text is None else text}]
        d["candidates"] = [{"content": {"role": "model", "parts": parts},
                            "finishReason": finish}]
    return genai_types.GenerateContentResponse.model_validate(d)


def gm(result, **opts):
    p = GeminiProvider(KEY, "gemini-test", **opts)
    rec = Recorder(result)
    p.client.models.generate_content = rec
    return p, rec


def test_gemini_normal_answer_and_usage():
    p, rec = gm(gm_response())
    c = p.complete_json("SYS", "USER", assist.SCHEMA, max_tokens=700)
    assert c.data == ANSWER
    u = c.usage
    assert (u.tokens_in, u.tokens_out, u.cache_read, u.cache_write) == (700, 150, 300, 0)
    assert u.model_served == "gemini-test-001"
    kw = rec.calls[0]
    assert kw["model"] == "gemini-test" and kw["contents"] == "USER"
    cfg = kw["config"]
    assert cfg.system_instruction == "SYS" and cfg.max_output_tokens == 700
    assert cfg.response_mime_type == "application/json"
    assert cfg.response_json_schema == assist.SCHEMA and cfg.response_schema is None
    assert cfg.thinking_config is None


def test_gemini_thinking_level_option_sent():
    p, rec = gm(gm_response(), thinking_level="low")
    p.complete_json("s", "u", triage.SCHEMA)
    assert rec.calls[0]["config"].thinking_config.thinking_level == genai_types.ThinkingLevel.LOW


@pytest.mark.parametrize("resp", [
    pytest.param(lambda: gm_response(block="SAFETY"), id="prompt-blocked"),
    pytest.param(lambda: gm_response(text="", finish="SAFETY"), id="finish-safety"),
    pytest.param(lambda: gm_response(text="", finish="PROHIBITED_CONTENT"), id="prohibited"),
])
def test_gemini_safety_block_is_refusal(resp):
    p, _ = gm(resp())
    with pytest.raises(ProviderRefusal):
        p.complete_json("s", "u", triage.SCHEMA)


def test_gemini_truncation():
    p, _ = gm(gm_response(text='{"bucket": "fy', finish="MAX_TOKENS"))
    with pytest.raises(ProviderError, match="max_output_tokens") as ei:
        p.complete_json("s", "u", triage.SCHEMA)
    assert not isinstance(ei.value, ProviderRefusal)


@pytest.mark.parametrize("exc, expect", [
    (lambda: genai_errors.ClientError(400, {"error": {"code": 400, "message": BODY_SECRET,
                                                      "status": "INVALID_ARGUMENT"}}),
     "gemini 400: INVALID_ARGUMENT"),
    (lambda: genai_errors.ServerError(503, {"error": {"code": 503, "message": BODY_SECRET,
                                                      "status": "UNAVAILABLE"}}),
     "gemini 503: UNAVAILABLE"),
    (lambda: httpx2.ConnectError("dns failure"), "gemini: connection error"),
])
def test_gemini_api_errors_carry_status_not_body(exc, expect):
    p, _ = gm(exc())
    with pytest.raises(ProviderError) as ei:
        p.complete_json("s", "u", triage.SCHEMA)
    assert str(ei.value) == expect
    assert BODY_SECRET not in str(ei.value) and not isinstance(ei.value, ProviderRefusal)


@pytest.mark.parametrize("text", ["not json {", '"just a string"'])
def test_gemini_invalid_json(text):
    p, _ = gm(gm_response(text=text))
    with pytest.raises(ProviderError, match="JSON"):
        p.complete_json("s", "u", triage.SCHEMA)


# ---------- schemas actually sent ----------

def _walk(node):
    if isinstance(node, dict):
        yield node
        for k, v in node.items():
            if k in ("properties", "$defs"):
                for sub in v.values():
                    yield from _walk(sub)
            elif k in ("items", "anyOf", "oneOf", "prefixItems", "additionalProperties"):
                yield from _walk(v)
    elif isinstance(node, list):
        for n in node:
            yield from _walk(n)


def assert_openai_strict(schema):
    assert schema["type"] == "object"
    objects = [n for n in _walk(schema) if n.get("type") == "object" or "properties" in n]
    assert objects
    for n in objects:
        assert n["additionalProperties"] is False
        assert sorted(n["required"]) == sorted(n["properties"])


def assert_gemini_ok(schema):
    for n in _walk(schema):
        assert set(n) <= SUPPORTED_KEYWORDS, set(n) - SUPPORTED_KEYWORDS
        for v in n.get("enum", []):
            assert isinstance(v, str | int | float) and not isinstance(v, bool)


@pytest.mark.parametrize("schema", SCHEMAS)
def test_openai_sends_strict_schema(schema):
    before = copy.deepcopy(schema)
    p, rec = oa(oa_response())
    p.complete_json("s", "u", schema)
    sent = rec.calls[0]["text"]["format"]["schema"]
    assert_openai_strict(sent)
    assert schema == before   # the caller's schema is never mutated


@pytest.mark.parametrize("schema", SCHEMAS)
def test_gemini_sends_supported_schema(schema):
    before = copy.deepcopy(schema)
    p, rec = gm(gm_response())
    p.complete_json("s", "u", schema)
    assert_gemini_ok(rec.calls[0]["config"].response_json_schema)
    assert schema == before


def test_strict_schema_makes_optional_nullable_and_closes_objects():
    loose = {"type": "object", "properties": {
        "a": {"type": "string"}, "b": {"type": "integer", "enum": [1, 2]},
        "c": {"type": "array", "items": {"type": "object", "properties": {"x": {"type": "string"}}}}},
        "required": ["a"]}
    s = strict_schema(loose)
    assert_openai_strict(s)
    assert s["properties"]["a"]["type"] == "string"
    assert s["properties"]["b"] == {"type": ["integer", "null"], "enum": [1, 2, None]}
    assert loose["required"] == ["a"] and "additionalProperties" not in loose


def test_gemini_schema_drops_unsupported_keywords():
    s = gemini_schema({"$schema": "x", "type": "object", "properties": {
        "a": {"type": "string", "pattern": "^x"}}, "required": ["a"]})
    assert s == {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}


# ---------- the key never shows ----------

@pytest.mark.parametrize("make", [lambda: OpenAIProvider(KEY, "gpt-test", effort="low"),
                                  lambda: GeminiProvider(KEY, "gemini-test")])
def test_api_key_never_in_repr_or_str(make):
    p = make()
    for text in (repr(p), str(p), f"{p}", repr([p])):
        assert KEY not in text and KEY[:12] not in text
