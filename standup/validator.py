"""
validator.py - Single source of truth for all input and config validation.

All validation rules for config files, CLI arguments, template strings, path
safety, and resource limits live here. Validator helpers return tuples instead
of raising, while argparse adapters raise ``ArgumentTypeError`` because that is
the mechanism argparse expects for user-facing CLI errors.
"""

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MAX_COMMIT_MESSAGE_LENGTH = 500
MAX_COMMITS_PER_RUN = 200
MAX_LLM_RESPONSE_LENGTH = 8000
MAX_REPO_COUNT = 20
MAX_CUSTOM_TEMPLATES = 10
MAX_HOURS_LOOKBACK = 720
MAX_HISTORY_LIMIT = 100
MAX_TEMPLATE_LENGTH = 2000
MAX_RENDERED_TEMPLATE_LENGTH = 10000
MAX_VARIABLE_VALUE_LENGTH = 5000
MAX_PATH_LENGTH = 4096

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SLACK_RE = re.compile(r"^https://hooks\.slack\.com/")
_URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$")
_NULL_BYTES_RE = re.compile(r"\x00")
_MULTI_SPACE_RE = re.compile(r" {2,}")
_TEMPLATE_TOKEN_RE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
_SAFE_TEMPLATE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,50}$")
_INVALID_TEMPLATE_SYNTAX_RE = re.compile(r"\{[^{}]*(?:!|:|\.)[^{}]*\}")

VALID_PROVIDERS = ("ollama", "groq")
VALID_TONES = ("casual", "formal")
VALID_TEMPLATE_VARIABLES = (
    "yesterday",
    "today",
    "blockers",
    "date",
    "time",
    "commit_count",
    "repos",
    "provider",
    "author_email",
)
KNOWN_GROQ_MODELS = (
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
    "mixtral-8x7b-32768",
    "llama3-8b-8192",
)


def sanitize_string(value: str, max_length: int = 500) -> str:
    """
    Normalize plain-text user input.

    Args:
        value: Raw user input.
        max_length: Maximum returned length.

    Returns:
        Sanitized text with null bytes removed and whitespace normalized.

    Raises:
        None.
    """
    if not isinstance(value, str):
        value = str(value)
    cleaned = _NULL_BYTES_RE.sub("", value)
    cleaned = cleaned.strip()
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned)
    return cleaned[:max_length]


def sanitize_path(path: str) -> str:
    """
    Normalize a filesystem path string.

    Args:
        path: Raw path-like value.

    Returns:
        Absolute normalized path string with null bytes removed.

    Raises:
        None.
    """
    if not isinstance(path, str):
        path = str(path)
    cleaned = _NULL_BYTES_RE.sub("", path).strip()
    if cleaned.startswith("\\\\") or cleaned.startswith("//"):
        return cleaned.replace("/", os.sep).replace("\\", os.sep)
    try:
        return str(Path(cleaned).expanduser().resolve())
    except (OSError, RuntimeError, ValueError):
        try:
            return str(Path(cleaned).expanduser().absolute())
        except (OSError, RuntimeError, ValueError):
            return cleaned


def validate_path_safety(path: str) -> Tuple[bool, str]:
    """
    Perform defense-in-depth validation for filesystem paths.

    Args:
        path: Path string to validate.

    Returns:
        Tuple of ``(is_valid, message)``.

    Raises:
        None.
    """
    if not isinstance(path, str) or not path.strip():
        return False, "Path must be a non-empty string."
    if "\x00" in path:
        return False, "Path must not contain null bytes."
    if len(path) > MAX_PATH_LENGTH:
        return False, "Path exceeds maximum length of {0} characters.".format(MAX_PATH_LENGTH)

    stripped = path.strip()
    if stripped.startswith("\\\\") or stripped.startswith("//"):
        return False, "Network paths are not allowed."

    sanitized = sanitize_path(stripped)
    candidate = Path(sanitized)
    if not candidate.is_absolute():
        return False, "Path must be absolute: {0}".format(path)

    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError, ValueError):
        return False, "Path could not be resolved safely."

    if str(resolved) != sanitized:
        return False, "Path contains unsafe traversal or normalization changes."

    if sys.platform != "win32" and candidate.exists() and candidate.is_symlink():
        try:
            parent_resolved = candidate.parent.resolve()
            target_resolved = candidate.resolve()
        except (OSError, RuntimeError, ValueError):
            return False, "Symlink target could not be resolved safely."
        if not _path_is_within(target_resolved, parent_resolved):
            return False, "Symlink paths must remain inside their parent directory."

    return True, ""


def _path_is_within(path: Path, parent: Path) -> bool:
    """
    Return whether a resolved path is inside a resolved parent directory.

    Args:
        path: Candidate path.
        parent: Parent directory boundary.

    Returns:
        ``True`` if ``path`` is equal to or nested under ``parent``.

    Raises:
        None.
    """
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_repo_path(path: str) -> Tuple[bool, str]:
    """
    Validate that a repo path is absolute, safe, and looks like a git repo.

    Args:
        path: Filesystem path to validate.

    Returns:
        Tuple of ``(is_valid, message)``.

    Raises:
        None.
    """
    if not path or not str(path).strip():
        return False, "Repo path must not be empty."

    ok, message = validate_path_safety(str(path))
    if not ok:
        return False, message

    repo_path = Path(sanitize_path(str(path)))
    if not repo_path.exists():
        return False, "Repo path does not exist: {0}".format(path)
    if not repo_path.is_dir():
        return False, "Repo path is not a directory: {0}".format(path)
    if not (repo_path / ".git").exists():
        return False, "Directory is not a git repository (no .git found): {0}".format(path)
    return True, ""


def validate_author_email(email: str) -> Tuple[bool, str]:
    """
    Validate author email format, allowing an empty value.

    Args:
        email: Configured git author filter email.

    Returns:
        Tuple of ``(is_valid, message)``.

    Raises:
        None.
    """
    if email == "":
        return True, ""
    if _EMAIL_RE.match(str(email)):
        return True, ""
    return False, "Invalid email format: {0!r}".format(email)


def validate_hours_lookback(value: Any) -> Tuple[bool, str]:
    """
    Validate a lookback hour value.

    Args:
        value: Candidate hour count.

    Returns:
        Tuple of ``(is_valid, message)``.

    Raises:
        None.
    """
    try:
        hours = int(value)
    except (TypeError, ValueError):
        return False, "hours_lookback must be an integer, got: {0!r}".format(value)
    if hours < 1 or hours > MAX_HOURS_LOOKBACK:
        return (
            False,
            "hours_lookback must be between 1 and {0}, got: {1}".format(
                MAX_HOURS_LOOKBACK, hours
            ),
        )
    return True, ""


def validate_tone(value: str) -> Tuple[bool, str]:
    """
    Validate the configured standup tone.

    Args:
        value: Tone value to validate.

    Returns:
        Tuple of ``(is_valid, message)``.

    Raises:
        None.
    """
    if not isinstance(value, str):
        return False, "tone must be a string, got: {0}".format(type(value).__name__)
    if value.strip().lower() in VALID_TONES:
        return True, ""
    return False, "tone must be one of {0}, got: {1!r}".format(VALID_TONES, value)


def validate_slack_webhook(url: str) -> Tuple[bool, str]:
    """
    Validate a Slack webhook URL, allowing an empty value.

    Args:
        url: Webhook URL to validate.

    Returns:
        Tuple of ``(is_valid, message)``.

    Raises:
        None.
    """
    if url == "":
        return True, ""
    if _SLACK_RE.match(str(url)):
        return True, ""
    return (
        False,
        "slack_webhook_url must start with 'https://hooks.slack.com/', got: {0!r}".format(url),
    )


def validate_boolean(value: Any, field_name: str) -> Tuple[bool, str]:
    """
    Validate that a config field is a boolean.

    Args:
        value: Value to validate.
        field_name: User-facing field name.

    Returns:
        Tuple of ``(is_valid, message)``.

    Raises:
        None.
    """
    if isinstance(value, bool):
        return True, ""
    return False, "{0} must be a boolean.".format(field_name)


def validate_rate_limit_config(rate_config: Any) -> Tuple[bool, str]:
    """
    Validate the ``rate_limit`` config block.

    Args:
        rate_config: Candidate config object.

    Returns:
        Tuple of ``(is_valid, message)``.

    Raises:
        None.
    """
    if not isinstance(rate_config, dict):
        return False, "rate_limit must be a JSON object."

    errors: List[str] = []

    ok, msg = validate_boolean(rate_config.get("enabled"), "rate_limit.enabled")
    if not ok:
        errors.append(msg)

    try:
        cooldown = int(rate_config.get("cooldown_minutes"))
        if cooldown < 0 or cooldown > 1440:
            errors.append("rate_limit.cooldown_minutes must be between 0 and 1440.")
    except (TypeError, ValueError):
        errors.append(
            "rate_limit.cooldown_minutes must be an integer, got: {0!r}".format(
                rate_config.get("cooldown_minutes")
            )
        )

    try:
        max_calls = int(rate_config.get("max_calls_per_day"))
        if max_calls < 1 or max_calls > 50:
            errors.append("rate_limit.max_calls_per_day must be between 1 and 50.")
    except (TypeError, ValueError):
        errors.append(
            "rate_limit.max_calls_per_day must be an integer, got: {0!r}".format(
                rate_config.get("max_calls_per_day")
            )
        )

    return (False, " | ".join(errors)) if errors else (True, "")


def validate_provider_config(provider_config: Any) -> Tuple[bool, str]:
    """
    Validate the provider config block.

    Args:
        provider_config: Candidate provider config.

    Returns:
        Tuple of ``(is_valid, message)``.

    Raises:
        None.
    """
    if not isinstance(provider_config, dict):
        return False, "provider must be a JSON object."

    name = provider_config.get("name", "")
    if name not in VALID_PROVIDERS:
        return False, "provider.name must be one of {0}, got: {1!r}".format(
            VALID_PROVIDERS, name
        )

    errors: List[str] = []

    ollama_cfg = provider_config.get("ollama", {})
    if not isinstance(ollama_cfg, dict):
        errors.append("provider.ollama must be a JSON object.")
    else:
        base_url = ollama_cfg.get("base_url", "")
        if not _URL_RE.match(str(base_url)):
            errors.append(
                "provider.ollama.base_url must be a valid URL, got: {0!r}".format(base_url)
            )
        model = ollama_cfg.get("model", "")
        if not isinstance(model, str) or not model.strip():
            errors.append("provider.ollama.model must be a non-empty string.")

    groq_cfg = provider_config.get("groq", {})
    if not isinstance(groq_cfg, dict):
        errors.append("provider.groq must be a JSON object.")
    else:
        groq_model = groq_cfg.get("model", "")
        if groq_model not in KNOWN_GROQ_MODELS:
            errors.append(
                "provider.groq.model must be one of {0}, got: {1!r}".format(
                    KNOWN_GROQ_MODELS, groq_model
                )
            )
        api_key = groq_cfg.get("api_key", "")
        if api_key and (not isinstance(api_key, str) or not api_key.startswith("gsk_")):
            errors.append("provider.groq.api_key must start with 'gsk_' when provided.")

    return (False, " | ".join(errors)) if errors else (True, "")


def validate_quality_config(quality_config: Any) -> Tuple[bool, str]:
    """
    Validate the ``quality`` config block.

    Args:
        quality_config: Candidate config object.

    Returns:
        Tuple of ``(is_valid, message)``.

    Raises:
        None.
    """
    if not isinstance(quality_config, dict):
        return False, "quality must be a JSON object."

    errors: List[str] = []

    ok, msg = validate_boolean(quality_config.get("enabled"), "quality.enabled")
    if not ok:
        errors.append(msg)

    ok, msg = validate_boolean(quality_config.get("show_breakdown"), "quality.show_breakdown")
    if not ok:
        errors.append(msg)

    try:
        min_score = int(quality_config.get("min_score"))
        if min_score < 0 or min_score > 100:
            errors.append("quality.min_score must be between 0 and 100.")
    except (TypeError, ValueError):
        errors.append(
            "quality.min_score must be an integer, got: {0!r}".format(
                quality_config.get("min_score")
            )
        )

    return (False, " | ".join(errors)) if errors else (True, "")


def validate_template_string(template_str: Any) -> Tuple[bool, str]:
    """
    Validate a custom template body.

    Args:
        template_str: Candidate template string.

    Returns:
        Tuple of ``(is_valid, message)``.

    Raises:
        None.
    """
    if not isinstance(template_str, str):
        return False, "Template must be a string."
    if not template_str.strip():
        return False, "Template must not be empty."
    if len(template_str) > MAX_TEMPLATE_LENGTH:
        return False, "Template must be {0} characters or fewer.".format(MAX_TEMPLATE_LENGTH)
    if "{{" in template_str or "}}" in template_str:
        return False, "Template must not contain nested braces."
    if _INVALID_TEMPLATE_SYNTAX_RE.search(template_str):
        return False, "Template must not use Python format specifiers or attribute access."

    tokens = _TEMPLATE_TOKEN_RE.findall(template_str)
    if not tokens:
        return False, "Template must contain at least one valid {variable} placeholder."

    invalid = sorted(set(token for token in tokens if token not in VALID_TEMPLATE_VARIABLES))
    if invalid:
        return False, "Template contains unsupported variables: {0}".format(", ".join(invalid))
    return True, ""


def validate_custom_templates_config(custom_templates: Any) -> Tuple[bool, str]:
    """
    Validate the ``custom_templates`` config block.

    Args:
        custom_templates: Candidate custom template mapping.

    Returns:
        Tuple of ``(is_valid, message)``.

    Raises:
        None.
    """
    if not isinstance(custom_templates, dict):
        return False, "custom_templates must be a JSON object."
    if len(custom_templates) > MAX_CUSTOM_TEMPLATES:
        return (
            False,
            "custom_templates must contain at most {0} templates.".format(
                MAX_CUSTOM_TEMPLATES
            ),
        )

    errors: List[str] = []
    for name, template_str in custom_templates.items():
        if not isinstance(name, str) or not _SAFE_TEMPLATE_NAME_RE.match(name):
            errors.append(
                "custom_templates keys must use letters, numbers, underscores, or dashes (max 50 chars)."
            )
            continue
        ok, msg = validate_template_string(template_str)
        if not ok:
            errors.append("custom_templates.{0}: {1}".format(name, msg))

    return (False, " | ".join(errors)) if errors else (True, "")


def validate_template_name(
    template_name: Any, custom_templates: Optional[Dict[str, str]] = None
) -> Tuple[bool, str]:
    """
    Validate that a selected template exists.

    Args:
        template_name: Template name to validate.
        custom_templates: Optional mapping of custom templates.

    Returns:
        Tuple of ``(is_valid, message)``.

    Raises:
        None.
    """
    if not isinstance(template_name, str) or not template_name.strip():
        return False, "template must be a non-empty string."
    available = {"default", "slack", "minimal", "detailed", "jira"}
    if isinstance(custom_templates, dict):
        available.update(custom_templates.keys())
    if template_name in available:
        return True, ""
    return False, "template must be one of {0}, got: {1!r}".format(sorted(available), template_name)


def validate_resource_limits(config: dict) -> Tuple[bool, List[str]]:
    """
    Validate that config does not request excessive resource consumption.

    Args:
        config: Full config dictionary.

    Returns:
        Tuple of ``(is_valid, errors)``.

    Raises:
        None.
    """
    errors: List[str] = []
    repos = config.get("repos", [])
    if isinstance(repos, list) and len(repos) > MAX_REPO_COUNT:
        errors.append("repos must contain at most {0} entries.".format(MAX_REPO_COUNT))

    custom_templates = config.get("custom_templates", {})
    if isinstance(custom_templates, dict) and len(custom_templates) > MAX_CUSTOM_TEMPLATES:
        errors.append(
            "custom_templates must contain at most {0} entries.".format(
                MAX_CUSTOM_TEMPLATES
            )
        )

    ok, msg = validate_hours_lookback(config.get("hours_lookback", 24))
    if not ok:
        errors.append(msg)

    return len(errors) == 0, errors


def validate_hours_arg(value: str) -> int:
    """
    ``argparse`` validator for ``--hours``.

    Args:
        value: CLI string value.

    Returns:
        Parsed integer hours value.

    Raises:
        argparse.ArgumentTypeError: If the value is invalid.
    """
    ok, msg = validate_hours_lookback(value)
    if not ok:
        raise argparse.ArgumentTypeError(msg.replace("hours_lookback", "--hours"))
    return int(value)


def validate_provider_arg(value: str) -> str:
    """
    ``argparse`` validator for ``--provider``.

    Args:
        value: CLI string value.

    Returns:
        Normalized provider slug.

    Raises:
        argparse.ArgumentTypeError: If the value is invalid.
    """
    lowered = str(value).lower()
    if lowered in VALID_PROVIDERS:
        return lowered
    raise argparse.ArgumentTypeError(
        "--provider must be 'ollama' or 'groq', got: {0!r}".format(value)
    )


def validate_positive_int_arg(
    field_name: str, value: str, minimum: int = 1, maximum: int = 200
) -> int:
    """
    Validate a positive integer CLI argument.

    Args:
        field_name: User-facing CLI flag name.
        value: CLI value string.
        minimum: Minimum permitted value.
        maximum: Maximum permitted value.

    Returns:
        Parsed integer value.

    Raises:
        argparse.ArgumentTypeError: If the value is invalid.
    """
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(
            "{0} must be an integer, got: {1!r}".format(field_name, value)
        )
    if parsed < minimum or parsed > maximum:
        raise argparse.ArgumentTypeError(
            "{0} must be between {1} and {2}.".format(field_name, minimum, maximum)
        )
    return parsed


def validate_cli_args(args: argparse.Namespace, config: dict) -> List[str]:
    """
    Perform cross-argument CLI validation.

    Args:
        args: Parsed CLI namespace.
        config: Loaded config dictionary.

    Returns:
        List of user-facing validation errors.

    Raises:
        None.
    """
    errors: List[str] = []

    if getattr(args, "hours", None) and getattr(args, "week", False):
        errors.append("--hours and --week are mutually exclusive.")

    if getattr(args, "slack", False):
        webhook = config.get("slack_webhook_url", "")
        if not webhook:
            errors.append("--slack requires slack_webhook_url to be set in config.")

    if getattr(args, "template", None):
        ok, msg = validate_template_name(getattr(args, "template"), config.get("custom_templates", {}))
        if not ok:
            errors.append(msg)

    if getattr(args, "command", "") == "history":
        if getattr(args, "clear", False) and getattr(args, "limit", None) not in (None, 10):
            errors.append("--limit cannot be combined with history --clear.")

    if getattr(args, "command", "") == "warm-up":
        if getattr(args, "install_startup", False) and getattr(
            args, "uninstall_startup", False
        ):
            errors.append("--install-startup and --uninstall-startup are mutually exclusive.")

    return errors


def validate_full_config(config: dict) -> Tuple[bool, List[str]]:
    """
    Validate the entire config and collect all errors.

    Args:
        config: Candidate config dictionary.

    Returns:
        Tuple of ``(is_valid, errors)``.

    Raises:
        None.
    """
    errors: List[str] = []

    repos = config.get("repos", [])
    if not isinstance(repos, list):
        errors.append("repos must be a JSON array.")
    else:
        for repo in repos:
            ok, msg = validate_repo_path(repo)
            if not ok:
                errors.append("repos: {0}".format(msg))

    ok, msg = validate_author_email(config.get("author_email", ""))
    if not ok:
        errors.append("author_email: {0}".format(msg))

    ok, msg = validate_hours_lookback(config.get("hours_lookback", 24))
    if not ok:
        errors.append("hours_lookback: {0}".format(msg))

    ok, msg = validate_tone(config.get("tone", "casual"))
    if not ok:
        errors.append("tone: {0}".format(msg))

    ok, msg = validate_slack_webhook(config.get("slack_webhook_url", ""))
    if not ok:
        errors.append("slack_webhook_url: {0}".format(msg))

    ok, msg = validate_provider_config(config.get("provider", {}))
    if not ok:
        errors.append("provider: {0}".format(msg))

    ok, msg = validate_rate_limit_config(config.get("rate_limit", {}))
    if not ok:
        errors.append("rate_limit: {0}".format(msg))

    ok, msg = validate_quality_config(
        config.get("quality", {"enabled": True, "min_score": 0, "show_breakdown": False})
    )
    if not ok:
        errors.append("quality: {0}".format(msg))

    ok, msg = validate_template_name(config.get("template", "default"), config.get("custom_templates", {}))
    if not ok:
        errors.append("template: {0}".format(msg))

    ok, msg = validate_custom_templates_config(config.get("custom_templates", {}))
    if not ok:
        errors.append("custom_templates: {0}".format(msg))

    ok, msg = validate_boolean(config.get("noise_filter_enabled", True), "noise_filter_enabled")
    if not ok:
        errors.append(msg)

    ok, msg = validate_boolean(config.get("auto_warm_up", False), "auto_warm_up")
    if not ok:
        errors.append(msg)

    resources_ok, resource_errors = validate_resource_limits(config)
    if not resources_ok:
        errors.extend(resource_errors)

    return len(errors) == 0, errors


def validate_setup_input(field: str, raw_input: str) -> Tuple[bool, str]:
    """
    Dispatch setup-wizard validation by field name.

    Args:
        field: Setup field name.
        raw_input: User-entered value.

    Returns:
        Tuple of ``(is_valid, message)``.

    Raises:
        None.
    """
    dispatch = {
        "repo_path": lambda value: validate_repo_path(sanitize_path(value)),
        "author_email": lambda value: validate_author_email(sanitize_string(value)),
        "hours_lookback": lambda value: validate_hours_lookback(sanitize_string(value)),
        "tone": lambda value: validate_tone(sanitize_string(value)),
        "slack_webhook_url": lambda value: validate_slack_webhook(sanitize_string(value)),
        "cooldown_minutes": _validate_cooldown_minutes,
        "max_calls_per_day": _validate_max_calls,
        "provider_name": _validate_provider_name,
        "ollama_model": _validate_ollama_model,
        "ollama_base_url": _validate_ollama_base_url,
        "groq_model": _validate_groq_model,
        "groq_api_key": _validate_groq_api_key_field,
        "quality_enabled": _validate_boolean_text,
        "quality_min_score": _validate_quality_min_score,
        "quality_show_breakdown": _validate_boolean_text,
        "noise_filter_enabled": _validate_boolean_text,
        "auto_warm_up": _validate_boolean_text,
        "template": _validate_template_selection,
    }
    validator = dispatch.get(field)
    if validator is None:
        return False, "Unknown field: {0!r}".format(field)
    return validator(raw_input)


def _validate_cooldown_minutes(value: str) -> Tuple[bool, str]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return False, "cooldown_minutes must be an integer, got: {0!r}".format(value)
    if parsed < 0 or parsed > 1440:
        return False, "cooldown_minutes must be between 0 and 1440."
    return True, ""


def _validate_max_calls(value: str) -> Tuple[bool, str]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return False, "max_calls_per_day must be an integer, got: {0!r}".format(value)
    if parsed < 1 or parsed > 50:
        return False, "max_calls_per_day must be between 1 and 50."
    return True, ""


def _validate_provider_name(value: str) -> Tuple[bool, str]:
    lowered = sanitize_string(value).lower()
    if lowered in VALID_PROVIDERS:
        return True, ""
    return False, "provider must be one of {0}, got: {1!r}".format(VALID_PROVIDERS, value)


def _validate_ollama_model(value: str) -> Tuple[bool, str]:
    normalized = sanitize_string(value)
    if normalized:
        return True, ""
    return False, "ollama model must be a non-empty string."


def _validate_ollama_base_url(value: str) -> Tuple[bool, str]:
    normalized = sanitize_string(value)
    if _URL_RE.match(normalized):
        return True, ""
    return False, "ollama base_url must be a valid URL, got: {0!r}".format(normalized)


def _validate_groq_model(value: str) -> Tuple[bool, str]:
    normalized = sanitize_string(value)
    if normalized in KNOWN_GROQ_MODELS:
        return True, ""
    return False, "groq model must be one of {0}, got: {1!r}".format(KNOWN_GROQ_MODELS, normalized)


def _validate_groq_api_key_field(value: str) -> Tuple[bool, str]:
    normalized = sanitize_string(value, max_length=200)
    if normalized == "":
        return True, ""
    if normalized.startswith("gsk_") and len(normalized) >= 40:
        return True, ""
    return False, "Groq API key must start with 'gsk_' and be at least 40 characters."


def _validate_boolean_text(value: str) -> Tuple[bool, str]:
    normalized = sanitize_string(value).lower()
    if normalized in ("true", "false", "yes", "no", "y", "n", "1", "0"):
        return True, ""
    return False, "Enter yes/no or true/false."


def _validate_quality_min_score(value: str) -> Tuple[bool, str]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return False, "quality.min_score must be an integer, got: {0!r}".format(value)
    if parsed < 0 or parsed > 100:
        return False, "quality.min_score must be between 0 and 100."
    return True, ""


def _validate_template_selection(value: str) -> Tuple[bool, str]:
    return validate_template_name(sanitize_string(value), {})


def parse_bool_text(value: str) -> bool:
    """
    Convert setup yes/no text into a boolean.

    Args:
        value: User-provided yes/no string.

    Returns:
        Boolean interpretation of the value.

    Raises:
        None.
    """
    return sanitize_string(value).lower() in ("true", "yes", "y", "1")
