"""
warmup.py - Pre-load the configured LLM model before the first standup run.
"""

from __future__ import annotations

import sys

import requests
from rich.console import Console

from standup.llm.base import BaseLLMProvider
from standup.llm.groq_provider import GroqProvider
from standup.llm.ollama_provider import OllamaProvider
from standup.logger import log_event
from standup.security import sanitize_error_message

console = Console()

_WARM_UP_PROMPT = "Reply with exactly one word: ready"


def is_model_warm(provider: OllamaProvider) -> bool:
    """
    Return whether the configured Ollama model is loaded into memory.

    Args:
        provider: Configured Ollama provider instance.

    Returns:
        ``True`` when the model is already resident in Ollama memory.

    Raises:
        None.
    """
    try:
        resp = requests.get(f"{provider.base_url}/api/ps", timeout=3)
        if resp.status_code != 200:
            return False
        data = resp.json()
        running = [m.get("name", "") for m in data.get("models", [])]
        return any(
            name == provider.model or name.startswith(provider.model + ":")
            for name in running
        )
    except Exception:
        return False


def get_warm_up_script_content(provider_config: dict) -> str:
    """
    Return a platform-appropriate shell script that runs standup warm-up.

    Args:
        provider_config: Provider config block (must contain ``name`` key).

    Returns:
        Shell script string ready to write to disk.

    Raises:
        None.
    """
    provider_name = provider_config.get("name", "ollama")

    if sys.platform == "win32":
        return (
            f"# StandupBot warm-up script\n"
            f"# Provider: {provider_name}\n"
            "standup warm-up\n"
        )

    return (
        "#!/usr/bin/env bash\n"
        f"# StandupBot warm-up script\n"
        f"# Provider: {provider_name}\n"
        "standup warm-up\n"
    )


def warm_up_provider(provider: BaseLLMProvider, verbose: bool = True) -> bool:
    """
    Warm up a provider by delegating to the appropriate implementation.

    Args:
        provider: Provider instance to warm up.
        verbose: Whether to print status messages.

    Returns:
        ``True`` on success, ``False`` on failure.

    Raises:
        None.
    """
    if isinstance(provider, OllamaProvider):
        return warm_up_ollama(provider, verbose)
    if isinstance(provider, GroqProvider):
        return _warm_up_groq(provider, verbose)
    return _warm_up_generic(provider, verbose)


def warm_up_ollama(provider: OllamaProvider, verbose: bool = True) -> bool:
    """
    Warm up an Ollama provider by sending a lightweight generation request.

    Args:
        provider: Configured Ollama provider instance.
        verbose: Whether to print status messages.

    Returns:
        ``True`` on success, ``False`` on failure.

    Raises:
        None.
    """
    if verbose:
        console.print(f"[dim]Warming up Ollama ({provider.model})...[/dim]")
    try:
        resp = requests.post(
            f"{provider.base_url}/api/generate",
            json={"model": provider.model, "prompt": _WARM_UP_PROMPT, "stream": False},
            timeout=30,
        )
        if resp.status_code == 200:
            if verbose:
                console.print(f"[green]Warm-up complete: Ollama ({provider.model})[/green]")
            log_event("warm_up_success", provider="ollama", model=provider.model)
            return True
        if verbose:
            console.print(f"[yellow]Warm-up returned HTTP {resp.status_code}.[/yellow]")
        log_event("warm_up_failed", provider="ollama", status_code=resp.status_code)
        return False
    except Exception as exc:
        if verbose:
            console.print(f"[yellow]Warm-up failed: {sanitize_error_message(exc)}[/yellow]")
        log_event("warm_up_failed", provider="ollama", error_type=type(exc).__name__)
        return False


def _warm_up_groq(provider: GroqProvider, verbose: bool = True) -> bool:
    """
    Warm up a Groq provider by checking availability.

    Args:
        provider: Configured Groq provider instance.
        verbose: Whether to print status messages.

    Returns:
        ``True`` when Groq is reachable, ``False`` otherwise.

    Raises:
        None.
    """
    if verbose:
        console.print("[dim]Checking Groq connectivity...[/dim]")
    try:
        if provider.is_available():
            if verbose:
                console.print("[green]Groq is reachable.[/green]")
            log_event("warm_up_success", provider="groq")
            return True
        if verbose:
            console.print("[yellow]Groq is not available.[/yellow]")
        log_event("warm_up_failed", provider="groq")
        return False
    except Exception as exc:
        if verbose:
            console.print(f"[yellow]Groq warm-up failed: {sanitize_error_message(exc)}[/yellow]")
        log_event("warm_up_failed", provider="groq", error_type=type(exc).__name__)
        return False


def _warm_up_generic(provider: BaseLLMProvider, verbose: bool = True) -> bool:
    """
    Warm up an unknown provider by checking availability.

    Args:
        provider: Any provider with an ``is_available`` method.
        verbose: Whether to print status messages.

    Returns:
        ``True`` when the provider reports itself as available.

    Raises:
        None.
    """
    try:
        available = provider.is_available()
        if verbose and available:
            console.print("[green]Provider is available.[/green]")
        log_event(
            "warm_up_success" if available else "warm_up_failed",
            provider=type(provider).__name__,
        )
        return available
    except Exception as exc:
        if verbose:
            console.print(f"[yellow]Warm-up failed: {sanitize_error_message(exc)}[/yellow]")
        log_event("warm_up_failed", provider=type(provider).__name__, error_type=type(exc).__name__)
        return False