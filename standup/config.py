"""
config.py - Load, validate, and save ``~/.standup.json`` configuration.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

from rich.console import Console

from standup.logger import log_event
from standup.security import sanitize_error_message
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
    "quality": {
        "enabled": True,
        "min_score": 0,
        "show_breakdown": False,
    },
    "noise_filter_enabled": True,
    "template": "default",
    "custom_templates": {},
    "auto_warm_up": False,
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into ``base`` and return a new dict."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict:
    """Load and validate the StandupBot config file."""
    from standup.security import enforce_file_permissions

    config_path = Path(CONFIG_PATH)

    if not config_path.exists():
        console.print(
            f"[yellow]⚠️  No config found at {CONFIG_PATH}. Using defaults. Run: standup --setup[/yellow]"
        )
        raw_config: Dict[str, Any] = {}
    else:
        enforce_file_permissions(CONFIG_PATH, label="Config file")
        try:
            raw_config = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            console.print(
                f"[red]❌ Invalid JSON in {CONFIG_PATH}: {sanitize_error_message(exc)}[/red]"
            )
            sys.exit(1)
        except OSError as exc:
            console.print(
                f"[red]❌ Could not read {CONFIG_PATH}: {sanitize_error_message(exc)}[/red]"
            )
            sys.exit(1)

    config = _deep_merge(_DEFAULTS, raw_config)

    env_key = os.environ.get("GROQ_API_KEY", "")
    if env_key:
        config["provider"]["groq"]["api_key"] = env_key

    ok, errors = validate_full_config(config)
    if not ok:
        log_event("config_validation_failed", error_count=len(errors))
        console.print("[red]❌ Config validation failed:[/red]")
        for error in errors:
            console.print(f"  [red]• {error}[/red]")
        console.print(f"\nFix your config at: {CONFIG_PATH}")
        console.print("Run [bold]standup --setup[/bold] to reconfigure.")
        sys.exit(1)

    valid_repos = []
    for repo in config.get("repos", []):
        repo_ok, message = validate_repo_path(repo)
        if repo_ok:
            valid_repos.append(repo)
        else:
            console.print(f"[yellow]⚠️  Skipping invalid repo: {message}[/yellow]")
    config["repos"] = valid_repos

    return config


def save_config(config: dict) -> None:
    """Write a config dict to disk and enforce secure file permissions."""
    from standup.security import enforce_file_permissions

    config_path = Path(CONFIG_PATH)
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    enforce_file_permissions(CONFIG_PATH, label="Config file")
    console.print(f"[green]✅ Config saved to {CONFIG_PATH}[/green]")