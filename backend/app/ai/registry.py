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


# Last observed AI result (in-process). Failures are never hidden: they are shown in Settings and on documents.
AI_STATUS: dict = {"last_ok_at": None, "last_error": None, "last_error_at": None, "last_provider": None}


def record_ai_result(provider_label: str, error: str | None) -> None:
    import datetime as _dt

    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    AI_STATUS["last_provider"] = provider_label
    if error:
        AI_STATUS["last_error"], AI_STATUS["last_error_at"] = error, now
    else:
        AI_STATUS["last_ok_at"] = now


def test_provider(name: str | None = None, model: str | None = None) -> dict:
    """Health check: one tiny real request to the configured provider."""
    import time

    from app.ai.base import AIProviderError

    p = get_provider(name, model)
    if not p.is_available():
        return {"ok": False, "provider": p.name, "model": p.model,
                "error": "No AI provider available — set an API key in .env (e.g. ANTHROPIC_API_KEY) and restart."}
    t0 = time.monotonic()
    try:
        text = p.complete("You are a health check.", "Reply with exactly: OK", 50)
    except AIProviderError as e:
        record_ai_result(p.label, str(e))
        return {"ok": False, "provider": p.name, "model": p.model, "error": str(e)}
    except Exception as e:  # unexpected SDK/network errors
        record_ai_result(p.label, f"{type(e).__name__}: {e}")
        return {"ok": False, "provider": p.name, "model": p.model, "error": f"{type(e).__name__}: {e}"}
    record_ai_result(p.label, None)
    return {"ok": True, "provider": p.name, "model": p.model, "latency_ms": round((time.monotonic() - t0) * 1000),
            "reply": text.strip()[:100]}


def provider_status(name: str | None = None, model: str | None = None) -> dict:
    env = get_settings()
    p = get_provider(name, model)
    return {
        "last": dict(AI_STATUS),
        "active": p.name, "model": p.model, "available": p.is_available(),
        "configured_keys": {"anthropic": bool(env.anthropic_api_key), "openai": bool(env.openai_api_key),
                            "google": bool(env.google_api_key)},
        "providers": PROVIDERS,
    }
