"""
llm/factory.py — Returns the correct LLM provider from config or CLI override.
"""

import sys
from typing import Optional

from rich.console import Console

from standup.llm.base import BaseLLMProvider
from standup.llm.groq_provider import GroqProvider
from standup.llm.ollama_provider import OllamaProvider

console = Console()

_VALID_PROVIDERS = ("ollama", "groq")


def get_provider(config: dict, override: Optional[str] = None) -> BaseLLMProvider:
    """
    Return the correct instantiated provider.

    Args:
        config: Full loaded config dict.
        override: Value from --provider CLI flag (one-time, does not modify config).

    Raises:
        ValueError: If provider name is unrecognized.
    """
    name = override if override else config.get("provider", {}).get("name", "ollama")
    name = name.lower()

    if name == "ollama":
        return OllamaProvider(config)
    if name == "groq":
        return GroqProvider(config)

    raise ValueError(
        f"Unknown provider: {name!r}. Valid options: {_VALID_PROVIDERS}"
    )


def get_provider_with_fallback(
    config: dict, override: Optional[str] = None
) -> BaseLLMProvider:
    """
    Get the configured/overridden provider, with automatic fallback to Groq
    when Ollama is configured but unavailable.

    Exits with code 1 if no provider is available.
    """
    try:
        provider = get_provider(config, override)
    except ValueError as exc:
        console.print(f"[red]❌ {exc}[/red]")
        sys.exit(1)

    if provider.is_available():
        return provider

    configured_name = (override or config.get("provider", {}).get("name", "ollama")).lower()

    # Only auto-fallback when Ollama is the configured provider
    if configured_name == "ollama":
        console.print(
            "[yellow]⚠️  Ollama not available, falling back to Groq...[/yellow]"
        )
        groq_provider = GroqProvider(config)
        if groq_provider.is_available():
            return groq_provider

        console.print(
            "[red]❌ Neither Ollama nor Groq is available.[/red]\n\n"
            "[bold]To fix Ollama:[/bold]\n"
            "  1. Install Ollama: https://ollama.com\n"
            "  2. Start it:       ollama serve\n"
            "  3. Pull a model:   ollama pull llama3\n\n"
            "[bold]To use Groq instead:[/bold]\n"
            "  1. Get a free key: https://console.groq.com\n"
            "  2. Set env var:    export GROQ_API_KEY=your_key\n"
            "  3. Update config:  provider.name = 'groq'\n"
        )
        sys.exit(1)

    # Groq configured but unavailable — no fallback
    console.print(
        "[red]❌ Groq is not available.[/red]\n"
        "Check your API key at: https://console.groq.com\n"
        "Make sure GROQ_API_KEY is set or provider.groq.api_key is in your config."
    )
    sys.exit(1)