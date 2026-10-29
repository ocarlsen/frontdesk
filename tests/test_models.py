"""Model choice in Ask: only vendors with keys are offered; Ask all fans out and survives one
model failing; vendor options never leak across vendors."""
from __future__ import annotations

import pytest

from frontdesk import providers
from frontdesk.items import Item, Message
from frontdesk.providers import Completion, ProviderError
from frontdesk.store import Store
from frontdesk.web import server

MODELS = [{"provider": "anthropic", "model": "a1", "label": "A"},
          {"provider": "openai", "model": "o1", "label": "O"},
          {"provider": "gemini", "model": "g1", "label": "G"}]


def settings(**over):
    return {"ask_models": MODELS, "owner_profile": "", "keychain_service": "k",
            "openai_keychain_service": "ko", "gemini_keychain_service": "kg",
            "provider_options": {"anthropic": {"effort": "medium"}}, **over}


def test_only_vendors_with_keys_are_offered(monkeypatch):
    monkeypatch.setattr(providers, "has_key", lambda s, name: name != "gemini")
    assert [m["label"] for m in server.available_models(settings())] == ["A", "O"]


class Fake:
    def __init__(self, provider, model, fail=False):
        self.name, self.model, self.fail = provider, model, fail

    def complete_json(self, system, user, schema, max_tokens=2048):
        if self.fail:
            raise ProviderError("quota")
        return Completion({"answer": f"{self.name} says hold off", "draft_reply": "",
                           "note_suggestions": []})


def test_ask_all_fans_out_and_reports_a_failure(tmp_path, monkeypatch):
    db = tmp_path / "m.db"
    s = Store(db)
    s.upsert_item(Item(id="gmail:t1", source="gmail", account="o@example.com", subject="x",
                       participants=["o@example.com", "f@example.com"],
                       updated_at="2026-10-28T16:00:00Z",
                       messages=[Message("F <f@example.com>", "2026-10-28T16:00:00Z", "hi")]))
    monkeypatch.setattr(providers, "get_provider",
                        lambda st: Fake(st["provider"], st["model"], fail=st["provider"] == "gemini"))
    out = server.ask_all(db, settings(), MODELS, "gmail:t1", "Thoughts?")
    got = {a["model"].split(" ")[0]: a for a in out["answers"]}
    assert got["A"]["answer"].startswith("anthropic") and got["O"]["answer"].startswith("openai")
    assert got["G"]["error"] == "quota"
    hist = Store(db).ask_history("gmail:t1")
    assert [h["role"] for h in hist] == ["owner", "assistant", "assistant"]   # question once


def test_vendor_options_stay_with_their_vendor(monkeypatch):
    seen = {}

    class Cap:
        def __init__(self, key, model, **opts):
            seen["opts"] = opts
    import types
    mod = types.SimpleNamespace(OpenAIProvider=Cap)
    monkeypatch.setattr("importlib.import_module", lambda name, pkg=None: mod)
    monkeypatch.setattr(providers, "api_key", lambda env, kc: "sk-test")
    providers.get_provider(settings(provider="openai", model="o1"))
    assert seen["opts"] == {}                      # Anthropic's effort did not leak


def test_unknown_provider_is_an_error():
    with pytest.raises(ValueError):
        providers.get_provider(settings(provider="mystery", model="x"))
