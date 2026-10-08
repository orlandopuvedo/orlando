"""Provider-neutral AI interface. The app must keep working with NO provider configured."""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod


class AIProviderError(RuntimeError):
    pass


class AIProvider(ABC):
    name: str = "base"
    default_model: str = ""

    def __init__(self, model: str | None = None):
        self.model = model or self.default_model

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def complete(self, system: str, prompt: str, max_tokens: int = 2000) -> str:
        """Return plain text. Raise AIProviderError on failure."""

    def complete_json(self, system: str, prompt: str, max_tokens: int = 4000) -> dict | list:
        text = self.complete(system + "\nRespond with valid JSON only, no prose, no code fences.", prompt, max_tokens)
        return extract_json(text)

    @property
    def label(self) -> str:
        return f"{self.name}:{self.model}" if self.model else self.name


class NullProvider(AIProvider):
    """Used when no AI is configured — callers fall back to deterministic templates."""

    name = "none"

    def is_available(self) -> bool:
        return False

    def complete(self, system: str, prompt: str, max_tokens: int = 2000) -> str:
        raise AIProviderError("No AI provider configured")


def extract_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        if m:
            return json.loads(m.group(1))
        raise AIProviderError("Model did not return JSON")
