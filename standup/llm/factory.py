"""
llm/factory.py - Instantiate the configured LLM provider with fallback logic.
"""

import sys

from rich.console import Console

from standup.llm.base import BaseLLMProvider
from standup.llm.groq_provider import GroqProvider
from standup.llm.ollama_provider import OllamaProvider
from standup.validator import VALID_PROVIDERS

console = Console()


def get_provider(config: dict, override: str | None = None) -> BaseLLMProvider:
    """
    Return an LLM provider instance for the given config.

    Args:
        config: Loaded application config.
        override: Optional one-time provider name override.

    Returns:
        Configured ``BaseLLMProvider`` subclass instance.

    Raises:
        ValueError: If the provider name is not recognised.
    """
    name = override or config.get("provider", {}).get("name", "ollama")
    if name == "ollama":
        return OllamaProvider(config)
    if name == "groq":
        return GroqProvider(config)
    raise ValueError(
        f"Unknown provider: {name!r}. Must be one of {VALID_PROVIDERS}."
    )


def get_provider_with_fallback(
    config: dict, override: str | None = None
) -> BaseLLMProvider:
    """
    Return an LLM provider, falling back to Groq when Ollama is unavailable.

    Args:
        config: Loaded application config.
        override: Optional one-time provider name override.

    Returns:
        The first available ``BaseLLMProvider`` instance.

    Raises:
        SystemExit: If no configured provider is available.
    """
    name = override or config.get("provider", {}).get("name", "ollama")

    if name not in VALID_PROVIDERS:
        console.print(
            f"[red]Unknown provider: {name!r}. Must be one of {VALID_PROVIDERS}.[/red]"
        )
        sys.exit(1)

    if name == "ollama":
        provider = OllamaProvider(config)
        if provider.is_available():
            return provider
        # Attempt Groq fallback — rely on is_available() to determine
        # whether Groq can actually serve requests.
        console.print(
            "[yellow]Ollama is not available. Falling back to Groq.[/yellow]"
        )
        groq_provider = GroqProvider(config)
        if groq_provider.is_available():
            return groq_provider
        console.print(
            "[red]Ollama is not running and Groq is also unavailable.[/red]\n"
            "Start Ollama: [bold]ollama serve[/bold]\n"
            "Or configure Groq: [bold]standup --setup[/bold]"
        )
        sys.exit(1)

    provider = GroqProvider(config)
    if provider.is_available():
        return provider
    console.print(
        "[red]Groq is not available. Check your API key and internet connection.[/red]"
    )
    sys.exit(1)