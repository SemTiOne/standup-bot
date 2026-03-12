"""
llm/groq_provider.py — Groq free cloud LLM provider.
"""

import os

from standup.llm.base import BaseLLMProvider, LLMProviderError

_SYSTEM_PROMPT = (
    "You are a helpful assistant that generates concise daily standup summaries "
    "for software engineers. Always respond in exactly this format:\n\n"
    "**Yesterday:** <what was done>\n"
    "**Today:** <what is planned>\n"
    "**Blockers:** <any blockers, or 'None'>\n\n"
    "Keep responses focused and professional."
)

GROQ_SIGNUP_URL = "https://console.groq.com"


class GroqProvider(BaseLLMProvider):
    """LLM provider that uses Groq's free cloud API."""

    def __init__(self, config: dict) -> None:
        groq_cfg = config.get("provider", {}).get("groq", {})
        # Environment variable takes priority
        self.api_key: str = os.environ.get("GROQ_API_KEY", "") or groq_cfg.get("api_key", "")
        self.model: str = groq_cfg.get("model", "llama-3.1-8b-instant")

    # ------------------------------------------------------------------

    def generate_standup(self, prompt: str, tone: str) -> str:
        """Call Groq chat completions API and return standup text."""
        if not self.api_key:
            raise LLMProviderError(
                f"Groq API key is invalid or missing. Get a free key at: {GROQ_SIGNUP_URL}"
            )

        try:
            from groq import Groq  # type: ignore[import]
        except ImportError as exc:
            raise LLMProviderError(
                "The 'groq' Python package is not installed. "
                "Run: pip install groq"
            ) from exc

        system = _SYSTEM_PROMPT
        if tone == "formal":
            system += "\nUse a formal, professional tone."
        else:
            system += "\nUse a casual, friendly tone."

        try:
            client = Groq(api_key=self.api_key, timeout=30.0)
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                model=self.model,
            )
            return chat_completion.choices[0].message.content
        except Exception as exc:
            msg = str(exc).lower()
            if "401" in msg or "invalid api key" in msg or "authentication" in msg:
                raise LLMProviderError(
                    f"Groq API key is invalid or missing. Get a free key at: {GROQ_SIGNUP_URL}"
                ) from exc
            if "429" in msg or "rate limit" in msg:
                raise LLMProviderError(
                    "Groq free tier rate limit hit. Wait a moment and try again, or switch to Ollama."
                ) from exc
            raise LLMProviderError(f"Groq error: {exc}") from exc

    def is_available(self) -> bool:
        """Return True if API key exists and Groq is reachable."""
        if not self.api_key:
            return False
        try:
            from groq import Groq  # type: ignore[import]
            client = Groq(api_key=self.api_key, timeout=5.0)
            # Lightweight check: list models
            client.models.list()
            return True
        except Exception:
            return False

    def get_provider_name(self) -> str:
        return f"Groq ({self.model})"