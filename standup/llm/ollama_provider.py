"""
llm/ollama_provider.py - Ollama local LLM provider.
"""

import requests

from standup.llm.base import DEFAULT_SYSTEM_PROMPT, BaseLLMProvider, LLMProviderError
from standup.logger import log_event
from standup.validator import MAX_LLM_RESPONSE_LENGTH

_OLLAMA_REQUEST_TIMEOUT = 60.0


class OllamaProvider(BaseLLMProvider):
    """LLM provider that uses a local Ollama instance."""

    def __init__(self, config: dict) -> None:
        ollama_cfg = config.get("provider", {}).get("ollama", {})
        self.base_url: str = ollama_cfg.get("base_url", "http://localhost:11434").rstrip("/")
        self.model: str = ollama_cfg.get("model", "llama3")

    def generate_standup(self, prompt: str, tone: str) -> str:
        """
        Call the Ollama chat API and return standup text.

        Args:
            prompt: Prompt text sent to the provider.
            tone: Requested standup tone.

        Returns:
            Provider response capped to safe length.

        Raises:
            LLMProviderError: If Ollama cannot satisfy the request.
        """
        try:
            import ollama  # type: ignore[import]
        except ImportError as exc:
            raise LLMProviderError(
                "The 'ollama' Python package is not installed. Run: pip install ollama"
            ) from exc

        system = DEFAULT_SYSTEM_PROMPT
        if tone == "formal":
            system += "\nUse a formal, professional tone."
        else:
            system += "\nUse a casual, friendly tone."

        try:
            client = ollama.Client(host=self.base_url, timeout=_OLLAMA_REQUEST_TIMEOUT)
            response = client.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            )
            content = response["message"]["content"] or ""
            if len(content) > MAX_LLM_RESPONSE_LENGTH:
                log_event("llm_response_truncated", provider="ollama", model=self.model)
                content = content[:MAX_LLM_RESPONSE_LENGTH]
            return content
        except Exception as exc:
            log_event("llm_error", error_type=type(exc).__name__, provider="ollama")
            message = str(exc).lower()
            if "connection" in message or "refused" in message or "cannot connect" in message:
                raise LLMProviderError(
                    "Ollama is not running. Start it with: ollama serve"
                ) from exc
            if "not found" in message or "model" in message:
                raise LLMProviderError(
                    "Configured Ollama model is not available locally. Pull it before retrying."
                ) from exc
            raise LLMProviderError("Ollama could not generate a standup right now.") from exc

    def is_available(self) -> bool:
        """
        Return whether Ollama is running and the configured model is present.

        Args:
            None.

        Returns:
            ``True`` if the provider appears ready, otherwise ``False``.

        Raises:
            None.
        """
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=3)
            if resp.status_code != 200:
                return False
            data = resp.json()
            models = [model.get("name", "") for model in data.get("models", [])]
            return any(name == self.model or name.startswith(self.model + ":") for name in models)
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
        return f"Ollama ({self.model})"

    def list_local_models(self) -> list[str]:
        """
        Return the list of locally pulled model names.

        Args:
            None.

        Returns:
            List of local model names.

        Raises:
            None.
        """
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code != 200:
                return []
            data = resp.json()
            return [model.get("name", "") for model in data.get("models", [])]
        except Exception:
            return []
