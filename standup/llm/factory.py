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
        SystemExit: If the provider name is not recognised.
    """
    name = override or config.get("provider", {}).get("name", "ollama")
    if name == "ollama":
        return OllamaProvider(config)
    if name == "groq":
        return GroqProvider(config)
    console.print(
        f"[red]❌ Unknown provider: {name!r}. Must be one of {VALID_PROVIDERS}.[/red]"
    )
    sys.exit(1)


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
            f"[red]❌ Unknown provider: {name!r}. Must be one of {VALID_PROVIDERS}.[/red]"
        )
        sys.exit(1)

    if name == "ollama":
        provider = OllamaProvider(config)
        if provider.is_available():
            return provider
        groq_key = (
            config.get("provider", {}).get("groq", {}).get("api_key", "")
            or __import__("os").environ.get("GROQ_API_KEY", "")
        )
        if not groq_key:
            console.print(
                "[red]❌ Ollama is not running and no Groq API key is configured.[/red]\n"
                "Start Ollama: [bold]ollama serve[/bold]\n"
                "Or set up Groq: [bold]standup --setup[/bold]"
            )
            sys.exit(1)
        console.print(
            "[yellow]⚠️  Ollama is not available. Falling back to Groq.[/yellow]"
        )
        groq_provider = GroqProvider(config)
        if not groq_provider.is_available():
            console.print(
                "[red]❌ Groq is also unavailable. Check your API key and internet connection.[/red]"
            )
            sys.exit(1)
        return groq_provider

    provider = GroqProvider(config)
    if provider.is_available():
        return provider
    console.print(
        "[red]❌ Groq is not available. Check your API key and internet connection.[/red]"
    )
    sys.exit(1)