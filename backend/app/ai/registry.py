"""Resolve the active AI provider from Settings (DB) + environment variables (keys)."""
from __future__ import annotations

from app.ai.anthropic_provider import AnthropicProvider
from app.ai.base import AIProvider, NullProvider
from app.ai.http_providers import GoogleProvider, OllamaProvider, OpenAIProvider
from app.config import get_settings

PROVIDERS = ["auto", "anthropic", "openai", "google", "ollama", "none"]


def build_provider(name: str, model: str | None = None) -> AIProvider:
    env = get_settings()
    model = model or env.ai_model or None
    if name == "anthropic":
        return AnthropicProvider(env.anthropic_api_key, model)
    if name == "openai":
        return OpenAIProvider(env.openai_api_key, env.openai_base_url, model)
    if name == "google":
        return GoogleProvider(env.google_api_key, model)
    if name == "ollama":
        return OllamaProvider(env.ollama_base_url, model)
    return NullProvider()


def get_provider(name: str | None = None, model: str | None = None) -> AIProvider:
    env = get_settings()
    name = (name or env.ai_provider or "auto").lower()
    if name in ("", "auto"):
        name = env.ai_provider if env.ai_provider not in ("", "auto") else "auto"
    if name == "auto":
        for candidate in ("anthropic", "openai", "google"):
            p = build_provider(candidate, model)
            if p.is_available():
                return p
        return NullProvider()
    return build_provider(name, model)


def provider_status(name: str | None = None, model: str | None = None) -> dict:
    env = get_settings()
    p = get_provider(name, model)
    return {
        "active": p.name, "model": p.model, "available": p.is_available(),
        "configured_keys": {"anthropic": bool(env.anthropic_api_key), "openai": bool(env.openai_api_key),
                            "google": bool(env.google_api_key)},
        "providers": PROVIDERS,
    }
