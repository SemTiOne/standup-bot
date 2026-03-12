"""
config.py — Loads and validates ~/.standup.json configuration.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

from rich.console import Console

from standup.validator import validate_full_config, validate_repo_path

console = Console()

CONFIG_PATH = str(Path.home() / ".standup.json")
USAGE_PATH = str(Path.home() / ".standup_usage.json")

_DEFAULTS: Dict[str, Any] = {
    "repos": [],
    "author_email": "",
    "hours_lookback": 24,
    "tone": "casual",
    "slack_webhook_url": "",
    "provider": {
        "name": "ollama",
        "ollama": {
            "base_url": "http://localhost:11434",
            "model": "llama3",
        },
        "groq": {
            "api_key": "",
            "model": "llama-3.1-8b-instant",
        },
    },
    "rate_limit": {
        "cooldown_minutes": 30,
        "max_calls_per_day": 10,
        "enabled": True,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning new dict."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def load_config() -> dict:
    """
    Load ~/.standup.json, validate it, and return the merged config dict.

    Steps:
      1. Enforce file permissions (chmod 600 on Unix).
      2. Load JSON from disk (or use defaults if file missing).
      3. Resolve Groq API key (env var takes priority).
      4. Deep-merge with defaults to fill missing keys.
      5. Validate with validate_full_config() — exits on any error.
      6. Skip invalid repo paths with a warning (don't crash).
    """
    from standup.security import enforce_config_permissions

    cfg_path = Path(CONFIG_PATH)

    if not cfg_path.exists():
        console.print(
            f"[yellow]⚠️  No config found at {CONFIG_PATH}. "
            "Using defaults. Run: standup --setup[/yellow]"
        )
        raw: dict = {}
    else:
        enforce_config_permissions(CONFIG_PATH)
        try:
            raw = json.loads(cfg_path.read_text())
        except json.JSONDecodeError as exc:
            console.print(f"[red]❌ Invalid JSON in {CONFIG_PATH}: {exc}[/red]")
            sys.exit(1)
        except OSError as exc:
            console.print(f"[red]❌ Could not read {CONFIG_PATH}: {exc}[/red]")
            sys.exit(1)

    # Deep-merge with defaults
    config = _deep_merge(_DEFAULTS, raw)

    # Resolve Groq API key: env var takes priority
    env_key = os.environ.get("GROQ_API_KEY", "")
    if env_key:
        config["provider"]["groq"]["api_key"] = env_key

    # Validate
    ok, errors = validate_full_config(config)
    if not ok:
        console.print("[red]❌ Config validation failed:[/red]")
        for err in errors:
            console.print(f"  [red]• {err}[/red]")
        console.print(f"\nFix your config at: {CONFIG_PATH}")
        console.print("Run [bold]standup --setup[/bold] to reconfigure.")
        sys.exit(1)

    # Skip invalid repo paths with warning
    valid_repos = []
    for repo in config.get("repos", []):
        ok_r, msg = validate_repo_path(repo)
        if ok_r:
            valid_repos.append(repo)
        else:
            console.print(f"[yellow]⚠️  Skipping invalid repo: {msg}[/yellow]")
    config["repos"] = valid_repos

    return config


def save_config(config: dict) -> None:
    """Write config dict to ~/.standup.json and enforce permissions."""
    from standup.security import enforce_config_permissions

    cfg_path = Path(CONFIG_PATH)
    cfg_path.write_text(json.dumps(config, indent=2))
    enforce_config_permissions(CONFIG_PATH)
    console.print(f"[green]✅ Config saved to {CONFIG_PATH}[/green]")