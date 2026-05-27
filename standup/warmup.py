"""
warmup.py - Pre-load provider models to reduce first-run latency.

The warm-up flow is intentionally lightweight so it can be used interactively,
silently before a standup run, or from a user-installed startup item.
"""

import sys
import time
from typing import TYPE_CHECKING, Dict

import requests
from rich.console import Console
from rich.status import Status

from standup.llm.groq_provider import GroqProvider
from standup.logger import log_event
from standup.security import sanitize_error_message

if TYPE_CHECKING:
    from standup.llm.base import BaseLLMProvider
    from standup.llm.ollama_provider import OllamaProvider

console = Console()


def warm_up_ollama(provider: "OllamaProvider", verbose: bool = False) -> bool:
    """
    Send a minimal request to Ollama so the configured model loads into memory.

    Args:
        provider: Configured Ollama provider instance.
        verbose: Whether to print timing details.

    Returns:
        ``True`` on success, otherwise ``False``.

    Raises:
        None.
    """
    started = time.perf_counter()
    try:
        with Status(
            "[bold cyan]Warming up Ollama model...[/bold cyan]",
            spinner="dots",
            console=console,
        ):
            response = requests.post(
                f"{provider.base_url}/api/generate",
                json={
                    "model": provider.model,
                    "prompt": "Respond with the single word READY.",
                    "stream": False,
                    "options": {"num_predict": 1},
                    "keep_alive": "10m",
                },
                timeout=60,
            )
        success = response.status_code == 200
    except Exception as exc:
        log_event("warm_up_completed", provider="ollama", duration_ms=0, success=False)
        if verbose:
            console.print(f"[yellow]⚠️  Warm-up failed: {sanitize_error_message(exc)}[/yellow]")
        return False

    elapsed = time.perf_counter() - started
    log_event(
        "warm_up_completed",
        provider="ollama",
        duration_ms=int(elapsed * 1000),
        success=success,
    )
    if success and verbose:
        console.print(f"[green]✅ Warm-up complete in {elapsed:.2f}s[/green]")
    elif not success and verbose:
        console.print(
            f"[yellow]⚠️  Warm-up request returned status {response.status_code} after {elapsed:.2f}s[/yellow]"
        )
    return success


def is_model_warm(provider: "OllamaProvider") -> bool:
    """
    Check whether the configured Ollama model appears in the process list.

    Args:
        provider: Configured Ollama provider instance.

    Returns:
        ``True`` when the model appears loaded, otherwise ``False``.

    Raises:
        None.
    """
    try:
        response = requests.get(f"{provider.base_url}/api/ps", timeout=5)
        if response.status_code != 200:
            return False
        data = response.json()
        models = data.get("models", [])
        for item in models:
            name = str(item.get("name", ""))
            if name == provider.model or name.startswith(provider.model + ":"):
                return True
        return False
    except Exception:
        return False


def warm_up_provider(provider: "BaseLLMProvider", verbose: bool = False) -> bool:
    """
    Warm up either Ollama or Groq using a provider-appropriate lightweight check.

    Args:
        provider: Provider instance to warm.
        verbose: Whether to print outcome details.

    Returns:
        ``True`` on success, otherwise ``False``.

    Raises:
        None.
    """
    try:
        from standup.llm.ollama_provider import OllamaProvider
    except Exception:
        OllamaProvider = None  # type: ignore[misc, assignment]  # noqa: N806

    if OllamaProvider is not None and isinstance(provider, OllamaProvider):
        return warm_up_ollama(provider, verbose=verbose)

    if isinstance(provider, GroqProvider):
        success = provider.is_available()
        log_event("warm_up_completed", provider="groq", duration_ms=0, success=success)
        if verbose:
            if success:
                console.print("[green]✅ Groq connectivity check succeeded[/green]")
            else:
                console.print("[yellow]⚠️  Groq warm-up ping failed[/yellow]")
        return success

    try:
        success = provider.is_available()
    except Exception:
        success = False

    log_event("warm_up_completed", provider="unknown", duration_ms=0, success=success)
    if verbose:
        if success:
            console.print("[green]✅ Provider warm-up check succeeded[/green]")
        else:
            console.print("[yellow]⚠️  Provider warm-up check failed[/yellow]")
    return success


def get_warm_up_script_content(provider_config: Dict[str, object]) -> str:
    """
    Build a shell script that runs the ``standup warm-up`` command.

    Args:
        provider_config: Provider config block used for informative comments.

    Returns:
        PowerShell or bash script content depending on the current platform.

    Raises:
        None.
    """
    provider_name = str(provider_config.get("name", "ollama"))
    if sys.platform == "win32":
        return (
            f"# StandupBot warm-up startup script\n# Provider: {provider_name}\nstandup warm-up\n"
        )
    return (
        "#!/usr/bin/env bash\n"
        "# StandupBot warm-up startup script\n"
        f"# Provider: {provider_name}\n"
        "standup warm-up\n"
    )
