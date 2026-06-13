"""
warmup.py - Pre-load the configured LLM model before the first standup run.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import requests
from rich.console import Console

from standup.logger import log_event
from standup.security import sanitize_error_message

if TYPE_CHECKING:
    from standup.llm.base import BaseLLMProvider
    from standup.llm.ollama_provider import OllamaProvider

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
    Return a shell script string that runs ``standup warm-up``.

    Args:
        provider_config: Provider config block.

    Returns:
        Platform-appropriate shell command string.

    Raises:
        None.
    """
    python_exe = sys.executable
    if sys.platform == "win32":
        return f'& "{python_exe}" -m standup.main warm-up'
    return f'"{python_exe}" -m standup.main warm-up'


def warm_up_provider(provider: BaseLLMProvider, verbose: bool = True) -> bool:
    """
    Send a lightweight prompt to load the model into memory.

    Args:
        provider: Provider instance to warm up.
        verbose: Whether to print status messages.

    Returns:
        ``True`` on success, ``False`` on failure.

    Raises:
        None.
    """
    from standup.llm.groq_provider import GroqProvider
    from standup.llm.ollama_provider import OllamaProvider

    if isinstance(provider, OllamaProvider):
        return _warm_up_ollama(provider, verbose)
    if isinstance(provider, GroqProvider):
        return _warm_up_groq(provider, verbose)
    return _warm_up_generic(provider, verbose)


def _warm_up_ollama(provider: OllamaProvider, verbose: bool) -> bool:
    if verbose:
        console.print(f"[dim]Warming up {provider.get_provider_name()}...[/dim]")
    try:
        resp = requests.post(
            f"{provider.base_url}/api/generate",
            json={"model": provider.model, "prompt": _WARM_UP_PROMPT, "stream": False},
            timeout=30,
        )
        if resp.status_code == 200:
            if verbose:
                console.print(f"[green]✅ {provider.get_provider_name()} is warm.[/green]")
            log_event("warm_up_success", provider="ollama", model=provider.model)
            return True
        if verbose:
            console.print(
                f"[yellow]⚠️  Warm-up returned HTTP {resp.status_code}.[/yellow]"
            )
        log_event("warm_up_failed", provider="ollama", status_code=resp.status_code)
        return False
    except Exception as exc:
        if verbose:
            console.print(
                f"[yellow]⚠️  Warm-up failed: {sanitize_error_message(exc)}[/yellow]"
            )
        log_event("warm_up_failed", provider="ollama", error_type=type(exc).__name__)
        return False


def _warm_up_groq(provider: GroqProvider, verbose: bool) -> bool:
    if verbose:
        console.print("[dim]Checking Groq connectivity...[/dim]")
    try:
        from groq import Groq  # type: ignore[import]

        client = Groq(api_key=provider.api_key, timeout=10.0)
        client.chat.completions.create(
            messages=[{"role": "user", "content": _WARM_UP_PROMPT}],
            model=provider.model,
            max_tokens=5,
        )
        if verbose:
            console.print("[green]✅ Groq is reachable.[/green]")
        log_event("warm_up_success", provider="groq")
        return True
    except Exception as exc:
        if verbose:
            console.print(
                f"[yellow]⚠️  Groq warm-up failed: {sanitize_error_message(exc)}[/yellow]"
            )
        log_event("warm_up_failed", provider="groq", error_type=type(exc).__name__)
        return False


def _warm_up_generic(provider: BaseLLMProvider, verbose: bool) -> bool:
    if verbose:
        console.print(f"[dim]Warming up {provider.get_provider_name()}...[/dim]")
    try:
        provider.generate_standup(_WARM_UP_PROMPT, "casual")
        if verbose:
            console.print("[green]✅ Provider responded.[/green]")
        log_event("warm_up_success", provider=provider.get_provider_name())
        return True
    except Exception as exc:
        if verbose:
            console.print(
                f"[yellow]⚠️  Warm-up failed: {sanitize_error_message(exc)}[/yellow]"
            )
        log_event("warm_up_failed", provider=provider.get_provider_name(), error_type=type(exc).__name__)
        return False