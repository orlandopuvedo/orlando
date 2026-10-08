from __future__ import annotations

from app.ai.base import AIProvider, AIProviderError


class AnthropicProvider(AIProvider):
    name = "anthropic"
    default_model = "claude-opus-5-5"

    def __init__(self, api_key: str | None, model: str | None = None):
        super().__init__(model)
        self.api_key = api_key

    def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def complete(self, system: str, prompt: str, max_tokens: int = 2000) -> str:
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover
            raise AIProviderError("Install the 'anthropic' package") from e
        client = anthropic.Anthropic(api_key=self.api_key)
        try:
            # Server-side fallback lets the API reroute a refused request to another model automatically.
            response = client.beta.messages.create(
                model=self.model,
                max_tokens=max(max_tokens, 4000),
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": "medium"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.RateLimitError as e:
            raise AIProviderError("Anthropic rate limit reached — try again shortly") from e
        except anthropic.APIStatusError as e:
            raise AIProviderError(f"Anthropic API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise AIProviderError("Could not reach the Anthropic API") from e
        if response.stop_reason == "refusal":
            raise AIProviderError("The model declined this request")
        text = "".join(b.text for b in response.content if b.type == "text")
        if not text.strip():
            raise AIProviderError("Empty response from model")
        return text
