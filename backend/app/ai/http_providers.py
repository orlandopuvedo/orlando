"""OpenAI, Google Gemini and local (Ollama) providers over their public REST APIs."""
from __future__ import annotations

import httpx

from app.ai.base import AIProvider, AIProviderError


class OpenAIProvider(AIProvider):
    name = "openai"
    default_model = "gpt-4o"

    def __init__(self, api_key: str | None, base_url: str, model: str | None = None):
        super().__init__(model)
        self.api_key, self.base_url = api_key, base_url.rstrip("/")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def complete(self, system: str, prompt: str, max_tokens: int = 2000) -> str:
        try:
            r = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "max_tokens": max_tokens,
                      "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]},
                timeout=120,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError) as e:
            raise AIProviderError(f"OpenAI request failed: {e}") from e


class GoogleProvider(AIProvider):
    name = "google"
    default_model = "gemini-2.0-flash"

    def __init__(self, api_key: str | None, model: str | None = None):
        super().__init__(model)
        self.api_key = api_key

    def is_available(self) -> bool:
        return bool(self.api_key)

    def complete(self, system: str, prompt: str, max_tokens: int = 2000) -> str:
        try:
            r = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                headers={"x-goog-api-key": self.api_key or ""},
                json={"systemInstruction": {"parts": [{"text": system}]},
                      "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                      "generationConfig": {"maxOutputTokens": max_tokens}},
                timeout=120,
            )
            r.raise_for_status()
            parts = r.json()["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        except (httpx.HTTPError, KeyError, IndexError) as e:
            raise AIProviderError(f"Google request failed: {e}") from e


class OllamaProvider(AIProvider):
    name = "ollama"
    default_model = "llama3.1"

    def __init__(self, base_url: str, model: str | None = None):
        super().__init__(model)
        self.base_url = base_url.rstrip("/")

    def is_available(self) -> bool:
        try:
            return httpx.get(f"{self.base_url}/api/tags", timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    def complete(self, system: str, prompt: str, max_tokens: int = 2000) -> str:
        try:
            r = httpx.post(
                f"{self.base_url}/api/chat",
                json={"model": self.model, "stream": False, "options": {"num_predict": max_tokens},
                      "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]},
                timeout=300,
            )
            r.raise_for_status()
            return r.json()["message"]["content"]
        except (httpx.HTTPError, KeyError) as e:
            raise AIProviderError(f"Ollama request failed: {e}") from e
