"""
llm/groq_provider.py - Groq free cloud LLM provider.
"""

import os

from standup.llm.base import DEFAULT_SYSTEM_PROMPT, BaseLLMProvider, LLMProviderError
from standup.logger import log_event
from standup.validator import MAX_LLM_RESPONSE_LENGTH

GROQ_SIGNUP_URL = "https://console.groq.com"


class GroqProvider(BaseLLMProvider):
    """LLM provider that uses Groq's free cloud API."""

    def __init__(self, config: dict) -> None:
        groq_cfg = config.get("provider", {}).get("groq", {})
        self.api_key: str = os.environ.get("GROQ_API_KEY", "") or groq_cfg.get("api_key", "")
        self.model: str = groq_cfg.get("model", "llama-3.1-8b-instant")

    def generate_standup(self, prompt: str, tone: str) -> str:
        """
        Call the Groq chat completions API and return standup text.

        Args:
            prompt: Prompt text sent to the provider.
            tone: Requested standup tone.

        Returns:
            Provider response capped to safe length.

        Raises:
            LLMProviderError: If Groq cannot satisfy the request.
        """
        if not self.api_key:
            raise LLMProviderError(
                f"Groq API key is invalid or missing. Get a free key at: {GROQ_SIGNUP_URL}"
            )

        try:
            from groq import Groq  # type: ignore[import]
        except ImportError as exc:
            raise LLMProviderError(
                "The 'groq' Python package is not installed. Run: pip install groq"
            ) from exc

        system = DEFAULT_SYSTEM_PROMPT
        if tone == "formal":
            system += "\nUse a formal, professional tone."
        else:
            system += "\nUse a casual, friendly tone."

        try:
            client = Groq(api_key=self.api_key, timeout=30.0)
            completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                model=self.model,
            )
            content = completion.choices[0].message.content or ""
            if len(content) > MAX_LLM_RESPONSE_LENGTH:
                log_event("llm_response_truncated", provider="groq", model=self.model)
                content = content[:MAX_LLM_RESPONSE_LENGTH]
            return content
        except Exception as exc:
            log_event("llm_error", error_type=type(exc).__name__, provider="groq")
            message = str(exc).lower()
            if "401" in message or "invalid api key" in message or "authentication" in message:
                raise LLMProviderError(
                    f"Groq API key is invalid or missing. Get a free key at: {GROQ_SIGNUP_URL}"
                ) from exc
            if "429" in message or "rate limit" in message:
                raise LLMProviderError(
                    "Groq free tier rate limit hit. Wait a moment and try again, or switch to Ollama."
                ) from exc
            raise LLMProviderError("Groq could not generate a standup right now.") from exc

    def is_available(self) -> bool:
        """
        Return whether an API key exists and Groq is reachable.

        Args:
            None.

        Returns:
            ``True`` if the provider appears ready, otherwise ``False``.

        Raises:
            None.
        """
        if not self.api_key:
            return False
        try:
            from groq import Groq  # type: ignore[import]

            client = Groq(api_key=self.api_key, timeout=5.0)
            client.models.list()
            return True
        except Exception:
            return False

    def get_provider_name(self) -> str:
        """
        Return a user-facing provider name.

        Args:
            None.

        Returns:
            Provider display name.

        Raises:
            None.
        """
        return f"Groq ({self.model})"
