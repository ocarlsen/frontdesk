"""Provider registry. The API key comes from the environment (e.g. ANTHROPIC_API_KEY) or, on
macOS, the Keychain, read at call time; FrontDesk never writes it to disk, logs it, or puts it
in settings."""
from __future__ import annotations

import os
import shutil
import subprocess

from .base import Provider, ProviderError, ProviderRefusal

__all__ = ["Provider", "ProviderError", "ProviderRefusal", "get_provider"]


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


def get_provider(settings: dict) -> Provider:
    name = settings["provider"]
    opts = settings["provider_options"]
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(api_key("ANTHROPIC_API_KEY", settings["keychain_service"]),
                                 settings["model"], **opts)
    raise ValueError(f"unknown provider '{name}' (known: anthropic)")
