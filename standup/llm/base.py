"""
llm/base.py — Abstract base class for all LLM providers.
"""

from abc import ABC, abstractmethod

# Shared system prompt used by every provider.
# Defined once here so updating it propagates everywhere automatically.
DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant that generates concise daily standup summaries "
    "for software engineers. Always respond in exactly this format:\n\n"
    "**Yesterday:** <what was done>\n"
    "**Today:** <what is planned>\n"
    "**Blockers:** <any blockers, or 'None'>\n\n"
    "Keep responses focused and professional."
)


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
