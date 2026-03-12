"""
llm/ollama_provider.py — Ollama local LLM provider.
"""

from typing import List

import requests

from standup.llm.base import BaseLLMProvider, LLMProviderError

_SYSTEM_PROMPT = (
    "You are a helpful assistant that generates concise daily standup summaries "
    "for software engineers. Always respond in exactly this format:\n\n"
    "**Yesterday:** <what was done>\n"
    "**Today:** <what is planned>\n"
    "**Blockers:** <any blockers, or 'None'>\n\n"
    "Keep responses focused and professional."
)


class OllamaProvider(BaseLLMProvider):
    """LLM provider that uses a local Ollama instance."""

    def __init__(self, config: dict) -> None:
        ollama_cfg = config.get("provider", {}).get("ollama", {})
        self.base_url: str = ollama_cfg.get("base_url", "http://localhost:11434").rstrip("/")
        self.model: str = ollama_cfg.get("model", "llama3")

    # ------------------------------------------------------------------

    def generate_standup(self, prompt: str, tone: str) -> str:
        """Call Ollama chat API and return standup text."""
        try:
            import ollama  # type: ignore[import]
        except ImportError as exc:
            raise LLMProviderError(
                "The 'ollama' Python package is not installed. "
                "Run: pip install ollama"
            ) from exc

        system = _SYSTEM_PROMPT
        if tone == "formal":
            system += "\nUse a formal, professional tone."
        else:
            system += "\nUse a casual, friendly tone."

        try:
            client = ollama.Client(host=self.base_url)
            response = client.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                options={"timeout": 60},
            )
            return response["message"]["content"]
        except Exception as exc:
            msg = str(exc).lower()
            if "connection" in msg or "refused" in msg or "cannot connect" in msg:
                raise LLMProviderError(
                    "Ollama is not running. Start it with: ollama serve"
                ) from exc
            if "not found" in msg or "model" in msg:
                raise LLMProviderError(
                    f"Model '{self.model}' not found. Pull it with: ollama pull {self.model}"
                ) from exc
            raise LLMProviderError(f"Ollama error: {exc}") from exc

    def is_available(self) -> bool:
        """Return True if Ollama server is running and the model is pulled."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=3)
            if resp.status_code != 200:
                return False
            data = resp.json()
            models = [m.get("name", "") for m in data.get("models", [])]
            # model names may include ":latest" suffix
            return any(
                m == self.model or m.startswith(self.model + ":")
                for m in models
            )
        except Exception:
            return False

    def get_provider_name(self) -> str:
        return f"Ollama ({self.model})"

    def list_local_models(self) -> List[str]:
        """Return list of locally pulled model names."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code != 200:
                return []
            data = resp.json()
            return [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            return []