"""
validator.py — Single source of truth for all input and config validation.

All validator functions return Tuple[bool, str] and never raise exceptions.
"""

import argparse
import re
from pathlib import Path
from typing import Any, List, Tuple

# Precompiled regex patterns
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SLACK_RE = re.compile(r"^https://hooks\.slack\.com/")
_URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$")
_NULL_BYTES_RE = re.compile(r"\x00")
_MULTI_SPACE_RE = re.compile(r" {2,}")

VALID_PROVIDERS = ("ollama", "groq")
VALID_TONES = ("casual", "formal")
KNOWN_GROQ_MODELS = (
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
    "mixtral-8x7b-32768",
)


# ---------------------------------------------------------------------------
# Config Field Validators
# ---------------------------------------------------------------------------


def validate_repo_path(path: str) -> Tuple[bool, str]:
    """Validate that a path is an absolute, existing git repository."""
    if not path or not path.strip():
        return False, "Repo path must not be empty."
    p = Path(path)
    if not p.is_absolute():
        return False, f"Repo path must be absolute: {path}"
    if not p.exists():
        return False, f"Repo path does not exist: {path}"
    if not p.is_dir():
        return False, f"Repo path is not a directory: {path}"
    if not (p / ".git").exists():
        return False, f"Directory is not a git repository (no .git found): {path}"
    return True, ""


def validate_author_email(email: str) -> Tuple[bool, str]:
    """Validate email format or accept empty string."""
    if email == "":
        return True, ""
    if _EMAIL_RE.match(email):
        return True, ""
    return False, f"Invalid email format: {email!r}"


def validate_hours_lookback(value: Any) -> Tuple[bool, str]:
    """Validate hours lookback is an integer between 1 and 720."""
    try:
        hours = int(value)
    except (TypeError, ValueError):
        return False, f"hours_lookback must be an integer, got: {value!r}"
    if hours < 1 or hours > 720:
        return False, f"hours_lookback must be between 1 and 720, got: {hours}"
    return True, ""


def validate_tone(value: str) -> Tuple[bool, str]:
    """Validate tone is 'casual' or 'formal' (case-insensitive)."""
    if not isinstance(value, str):
        return False, f"tone must be a string, got: {type(value).__name__}"
    if value.strip().lower() in VALID_TONES:
        return True, ""
    return False, f"tone must be one of {VALID_TONES}, got: {value!r}"


def validate_slack_webhook(url: str) -> Tuple[bool, str]:
    """Validate Slack webhook URL (empty string is allowed)."""
    if url == "":
        return True, ""
    if _SLACK_RE.match(url):
        return True, ""
    return False, f"slack_webhook_url must start with 'https://hooks.slack.com/', got: {url!r}"


def validate_rate_limit_config(rate_config: Any) -> Tuple[bool, str]:
    """Validate rate_limit config block."""
    if not isinstance(rate_config, dict):
        return False, "rate_limit must be a JSON object."

    errors: List[str] = []

    enabled = rate_config.get("enabled")
    if not isinstance(enabled, bool):
        errors.append("rate_limit.enabled must be a boolean.")

    cooldown = rate_config.get("cooldown_minutes")
    try:
        c = int(cooldown)  # type: ignore[arg-type]
        if c < 0 or c > 1440:
            errors.append("rate_limit.cooldown_minutes must be between 0 and 1440.")
    except (TypeError, ValueError):
        errors.append(f"rate_limit.cooldown_minutes must be an integer, got: {cooldown!r}")

    max_calls = rate_config.get("max_calls_per_day")
    try:
        m = int(max_calls)  # type: ignore[arg-type]
        if m < 1 or m > 50:
            errors.append("rate_limit.max_calls_per_day must be between 1 and 50.")
    except (TypeError, ValueError):
        errors.append(f"rate_limit.max_calls_per_day must be an integer, got: {max_calls!r}")

    if errors:
        return False, " | ".join(errors)
    return True, ""


def validate_provider_config(provider_config: Any) -> Tuple[bool, str]:
    """Validate the full provider config block."""
    if not isinstance(provider_config, dict):
        return False, "provider must be a JSON object."

    name = provider_config.get("name", "")
    if name not in VALID_PROVIDERS:
        return False, f"provider.name must be one of {VALID_PROVIDERS}, got: {name!r}"

    errors: List[str] = []

    if name == "ollama":
        ollama_cfg = provider_config.get("ollama", {})
        if not isinstance(ollama_cfg, dict):
            errors.append("provider.ollama must be a JSON object.")
        else:
            base_url = ollama_cfg.get("base_url", "")
            if not _URL_RE.match(base_url):
                errors.append(f"provider.ollama.base_url must be a valid URL, got: {base_url!r}")
            model = ollama_cfg.get("model", "")
            if not isinstance(model, str) or not model.strip():
                errors.append("provider.ollama.model must be a non-empty string.")

    elif name == "groq":
        groq_cfg = provider_config.get("groq", {})
        if not isinstance(groq_cfg, dict):
            errors.append("provider.groq must be a JSON object.")
        else:
            model = groq_cfg.get("model", "")
            if model not in KNOWN_GROQ_MODELS:
                errors.append(
                    f"provider.groq.model must be one of {KNOWN_GROQ_MODELS}, got: {model!r}"
                )
            # api_key is optional in config (env var allowed)

    if errors:
        return False, " | ".join(errors)
    return True, ""


# ---------------------------------------------------------------------------
# CLI Argument Validators
# ---------------------------------------------------------------------------


def validate_hours_arg(value: str) -> int:
    """argparse type function for --hours."""
    try:
        hours = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"--hours must be an integer, got: {value!r}")
    if hours < 1 or hours > 720:
        raise argparse.ArgumentTypeError("--hours must be between 1 and 720.")
    return hours


def validate_provider_arg(value: str) -> str:
    """argparse type function for --provider."""
    if value.lower() in VALID_PROVIDERS:
        return value.lower()
    raise argparse.ArgumentTypeError(
        f"--provider must be 'ollama' or 'groq', got: {value!r}"
    )


def validate_cli_args(args: argparse.Namespace, config: dict) -> List[str]:
    """Cross-argument validation. Returns list of error strings."""
    errors: List[str] = []

    if getattr(args, "hours", None) and getattr(args, "week", False):
        errors.append("--hours and --week are mutually exclusive.")

    if getattr(args, "slack", False):
        webhook = config.get("slack_webhook_url", "")
        if not webhook:
            errors.append("--slack requires slack_webhook_url to be set in config.")

    return errors


# ---------------------------------------------------------------------------
# Config-wide Validator
# ---------------------------------------------------------------------------


def validate_full_config(config: dict) -> Tuple[bool, List[str]]:
    """Validate entire config and report ALL errors at once."""
    errors: List[str] = []

    # repos
    repos = config.get("repos", [])
    if not isinstance(repos, list):
        errors.append("repos must be a JSON array.")
    else:
        for repo in repos:
            ok, msg = validate_repo_path(repo)
            if not ok:
                errors.append(f"repos: {msg}")

    # author_email
    ok, msg = validate_author_email(config.get("author_email", ""))
    if not ok:
        errors.append(f"author_email: {msg}")

    # hours_lookback
    ok, msg = validate_hours_lookback(config.get("hours_lookback", 24))
    if not ok:
        errors.append(f"hours_lookback: {msg}")

    # tone
    ok, msg = validate_tone(config.get("tone", "casual"))
    if not ok:
        errors.append(f"tone: {msg}")

    # slack_webhook_url
    ok, msg = validate_slack_webhook(config.get("slack_webhook_url", ""))
    if not ok:
        errors.append(f"slack_webhook_url: {msg}")

    # provider
    ok, msg = validate_provider_config(config.get("provider", {}))
    if not ok:
        errors.append(f"provider: {msg}")

    # rate_limit
    ok, msg = validate_rate_limit_config(config.get("rate_limit", {}))
    if not ok:
        errors.append(f"rate_limit: {msg}")

    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# Setup Wizard Validators
# ---------------------------------------------------------------------------


def validate_setup_input(field: str, raw_input: str) -> Tuple[bool, str]:
    """Dispatch to correct validator by field name for the setup wizard."""
    dispatch = {
        "repo_path": lambda v: validate_repo_path(sanitize_path(v)),
        "author_email": lambda v: validate_author_email(sanitize_string(v)),
        "hours_lookback": lambda v: validate_hours_lookback(sanitize_string(v)),
        "tone": lambda v: validate_tone(sanitize_string(v)),
        "slack_webhook_url": lambda v: validate_slack_webhook(sanitize_string(v)),
        "cooldown_minutes": _validate_cooldown_minutes,
        "max_calls_per_day": _validate_max_calls,
        "provider_name": _validate_provider_name,
        "ollama_model": _validate_ollama_model,
        "ollama_base_url": _validate_ollama_base_url,
        "groq_model": _validate_groq_model,
        "groq_api_key": _validate_groq_api_key_field,
    }
    fn = dispatch.get(field)
    if fn is None:
        return False, f"Unknown field: {field!r}"
    return fn(raw_input)


def _validate_cooldown_minutes(value: str) -> Tuple[bool, str]:
    try:
        v = int(value)
        if v < 0 or v > 1440:
            return False, "cooldown_minutes must be between 0 and 1440."
        return True, ""
    except (TypeError, ValueError):
        return False, f"cooldown_minutes must be an integer, got: {value!r}"


def _validate_max_calls(value: str) -> Tuple[bool, str]:
    try:
        v = int(value)
        if v < 1 or v > 50:
            return False, "max_calls_per_day must be between 1 and 50."
        return True, ""
    except (TypeError, ValueError):
        return False, f"max_calls_per_day must be an integer, got: {value!r}"


def _validate_provider_name(value: str) -> Tuple[bool, str]:
    if value.lower() in VALID_PROVIDERS:
        return True, ""
    return False, f"provider must be one of {VALID_PROVIDERS}, got: {value!r}"


def _validate_ollama_model(value: str) -> Tuple[bool, str]:
    v = sanitize_string(value)
    if v:
        return True, ""
    return False, "ollama model must be a non-empty string."


def _validate_ollama_base_url(value: str) -> Tuple[bool, str]:
    v = sanitize_string(value)
    if _URL_RE.match(v):
        return True, ""
    return False, f"ollama base_url must be a valid URL, got: {v!r}"


def _validate_groq_model(value: str) -> Tuple[bool, str]:
    v = sanitize_string(value)
    if v in KNOWN_GROQ_MODELS:
        return True, ""
    return False, f"groq model must be one of {KNOWN_GROQ_MODELS}, got: {v!r}"


def _validate_groq_api_key_field(value: str) -> Tuple[bool, str]:
    """Groq API key is optional; if provided, it must start with gsk_."""
    v = sanitize_string(value)
    if v == "":
        return True, ""
    if v.startswith("gsk_") and len(v) >= 40:
        return True, ""
    return False, "Groq API key must start with 'gsk_' and be at least 40 characters."


# ---------------------------------------------------------------------------
# Sanitization Helpers
# ---------------------------------------------------------------------------


def sanitize_string(value: str, max_length: int = 500) -> str:
    """Strip whitespace, collapse internal spaces, truncate, remove null bytes."""
    if not isinstance(value, str):
        value = str(value)
    value = _NULL_BYTES_RE.sub("", value)
    value = value.strip()
    value = _MULTI_SPACE_RE.sub(" ", value)
    return value[:max_length]


def sanitize_path(path: str) -> str:
    """Strip whitespace, expand ~, resolve to absolute path."""
    if not isinstance(path, str):
        path = str(path)
    path = path.strip()
    return str(Path(path).expanduser().resolve())