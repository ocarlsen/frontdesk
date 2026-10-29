"""Provider registry. The API key comes from the environment (e.g. ANTHROPIC_API_KEY) or, on
macOS, the Keychain, read at call time; FrontDesk never writes it to disk, logs it, or puts it
in settings."""
from __future__ import annotations

import os
import shutil
import subprocess

from .base import Completion, Provider, ProviderError, ProviderRefusal, Usage

__all__ = ["Completion", "Provider", "ProviderError", "ProviderRefusal", "Usage", "get_provider"]


def keychain_secret(service: str) -> str:
    if not shutil.which("security"):
        raise ProviderError(f"no API key: set the provider's key environment variable "
                            f"(macOS users can instead use Keychain item '{service}')")
    r = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                       capture_output=True, text=True)
    if r.returncode == 36:  # errSecInteractionNotAllowed: the item exists, the keychain is locked
        raise ProviderError(
            f"Keychain locked for this shell (SSH or tmux started outside the GUI login), so "
            f"'{service}' can't be read here. Run FrontDesk from a regular Terminal window.")
    if r.returncode != 0 or not r.stdout.strip():
        raise ProviderError(
            f"no Keychain item '{service}'. Store it from a regular Terminal with: "
            f"security add-generic-password -U -s {service} -a $USER -w")
    return r.stdout.strip()


def api_key(env_var: str, keychain_service: str) -> str:
    return os.environ.get(env_var, "").strip() or keychain_secret(keychain_service)


# provider -> (environment variable, settings key naming its Keychain item, adapter path)
VENDORS = {
    "anthropic": ("ANTHROPIC_API_KEY", "keychain_service", "anthropic_provider:AnthropicProvider"),
    "openai": ("OPENAI_API_KEY", "openai_keychain_service", "openai_provider:OpenAIProvider"),
    "gemini": ("GEMINI_API_KEY", "gemini_keychain_service", "gemini_provider:GeminiProvider"),
}


def has_key(settings: dict, name: str) -> bool:
    """Whether a key for this vendor is available, without returning it."""
    env, kc, _ = VENDORS[name]
    if os.environ.get(env, "").strip():
        return True
    try:
        return bool(keychain_secret(settings[kc]))
    except ProviderError:
        return False


def get_provider(settings: dict) -> Provider:
    """settings['provider'] and settings['model'] pick the adapter. Vendor-specific knobs live in
    settings['provider_options'][<provider>], so one vendor's options never reach another."""
    name = settings["provider"]
    if name not in VENDORS:
        raise ValueError(f"unknown provider '{name}' (known: {', '.join(VENDORS)})")
    env, kc, path = VENDORS[name]
    module, cls = path.split(":")
    import importlib
    try:
        adapter = getattr(importlib.import_module(f".{module}", __name__), cls)
    except ImportError as e:   # the vendor SDK is an optional extra
        raise ProviderError(f"{name} support is not installed: pip install 'frontdesk[{name}]'") \
            from e
    opts = (settings.get("provider_options") or {}).get(name, {})
    return adapter(api_key(env, settings[kc]), settings["model"], **opts)
