"""
llm/base.py — Abstract base class for all LLM providers.
"""

from abc import ABC, abstractmethod


class LLMProviderError(Exception):
    """Raised when an LLM provider fails to generate a response."""
    pass


class BaseLLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    @abstractmethod
    def generate_standup(self, prompt: str, tone: str) -> str:
        """
        Send prompt to the LLM and return the standup text.

        Must return a string in the format::

            **Yesterday:** ...
            **Today:** ...
            **Blockers:** ...

        Raises:
            LLMProviderError: on any failure.
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if this provider is reachable and ready.

        For Ollama: check if server is running and model is pulled.
        For Groq: check if API key is valid and reachable.

        Returns True/False without raising exceptions.
        """
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        """Return human-readable provider name, e.g. 'Ollama (llama3)'"""
        pass