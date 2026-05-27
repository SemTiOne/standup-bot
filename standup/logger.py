"""
logger.py - Structured file-based logging for StandupBot.

Writes JSON lines to ``~/.standup.log`` with automatic rotation. The logger is
careful to avoid recording secrets, commit content, LLM output, template text,
file paths, or user email addresses.
"""

import contextlib
import json
import logging
import os
import stat
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional

_LOGGER_NAME = "standupbot"
_LOG_FILE_NAME = ".standup.log"
_MAX_LOG_BYTES = 1024 * 1024
_BACKUP_COUNT = 3
_ROTATE_EARLY_BYTES = 500 * 1024
_SENSITIVE_SUBSTRINGS = (
    "key",
    "secret",
    "password",
    "token",
    "api",
    "email",
    "template",
    "prompt",
    "standup_text",
    "output",
    "path",
)
_SENSITIVE_EXACT_KEYS = frozenset(
    {
        "author_email",
        "commit_message",
        "error_message",
        "file_path",
        "llm_output",
        "prompt",
        "standup_text",
        "template_content",
    }
)
_SAFE_EXACT_KEYS = frozenset(
    {
        "cached",
        "commit_count",
        "duration_ms",
        "event",
        "health_score",
        "level",
        "model",
        "operation",
        "passed",
        "provider",
        "python_version",
        "quality_score",
        "repos",
        "seconds_remaining",
        "success",
        "tone",
        "version",
        "warned",
        "failed",
    }
)
_LOGGER: Optional[logging.Logger] = None


def get_log_path() -> str:
    """
    Return the absolute path to the application log file.

    Args:
        None.

    Returns:
        Absolute path to ``~/.standup.log``.

    Raises:
        None.
    """
    return str(Path.home() / _LOG_FILE_NAME)


def _enforce_permissions(file_path: str) -> None:
    """
    Restrict a file to user-only access on Unix platforms.

    Args:
        file_path: Absolute path to the file that should be protected.

    Returns:
        None.

    Raises:
        None.
    """
    path = Path(file_path)
    if not path.exists() or os.name == "nt":
        return
    try:
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            path.chmod(0o600)
    except OSError:
        return


def _sanitize_value(key: str, value: Any) -> Any:
    """
    Redact sensitive values before writing them to disk.

    Args:
        key: Structured field name associated with the value.
        value: Value supplied by the caller.

    Returns:
        Safe value for structured logging.

    Raises:
        None.
    """
    normalized_key = str(key).strip().lower()
    if normalized_key in _SAFE_EXACT_KEYS:
        return value
    if normalized_key in _SENSITIVE_EXACT_KEYS:
        return "[REDACTED]"
    for fragment in _SENSITIVE_SUBSTRINGS:
        if fragment in normalized_key:
            return "[REDACTED]"
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(normalized_key, item) for item in value]
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for nested_key, nested_value in value.items():
            sanitized[str(nested_key)] = _sanitize_value(str(nested_key), nested_value)
        return sanitized
    return value


def get_logger() -> logging.Logger:
    """
    Return the configured structured logger.

    Args:
        None.

    Returns:
        Configured ``logging.Logger`` instance.

    Raises:
        None.
    """
    global _LOGGER

    if _LOGGER is not None:
        return _LOGGER

    log_path = Path(get_log_path())
    with contextlib.suppress(OSError):
        log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        try:
            handler = RotatingFileHandler(
                str(log_path),
                maxBytes=_MAX_LOG_BYTES,
                backupCount=_BACKUP_COUNT,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)
            _enforce_permissions(str(log_path))
        except Exception:
            logger.addHandler(logging.NullHandler())

    _LOGGER = logger
    return logger


def log_event(event: str, **kwargs: Any) -> None:
    """
    Log a single structured event as JSON.

    Args:
        event: Event name to record.
        **kwargs: Additional structured fields. Sensitive fields are redacted
            automatically by key name.

    Returns:
        None.

    Raises:
        None.
    """
    try:
        payload: Dict[str, Any] = {
            "ts": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "level": "INFO",
            "event": str(event or "unknown"),
        }
        for key, value in kwargs.items():
            payload[str(key)] = _sanitize_value(str(key), value)
        get_logger().info(json.dumps(payload, ensure_ascii=True, sort_keys=True))
    except Exception:
        return


def read_log_entries(limit: int = 20) -> List[Dict[str, Any]]:
    """
    Read structured log entries from disk.

    Args:
        limit: Maximum number of recent entries to return.

    Returns:
        Parsed log entries ordered oldest-to-newest within the selected tail.

    Raises:
        None.
    """
    safe_limit = max(1, min(int(limit), 500))
    path = Path(get_log_path())
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    entries: List[Dict[str, Any]] = []
    for line in lines[-safe_limit:]:
        try:
            payload = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            entries.append(payload)
    return entries


def clear_logs() -> bool:
    """
    Truncate the application log file.

    Args:
        None.

    Returns:
        ``True`` when truncation succeeded or the file did not exist.

    Raises:
        None.
    """
    path = Path(get_log_path())
    try:
        path.write_text("", encoding="utf-8")
        _enforce_permissions(str(path))
        return True
    except OSError:
        return not path.exists()


def get_log_size_bytes() -> int:
    """
    Return the current log file size in bytes.

    Args:
        None.

    Returns:
        Size in bytes, or ``0`` when the file is missing.

    Raises:
        None.
    """
    path = Path(get_log_path())
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


def rotate_logs_if_needed(force_threshold_bytes: Optional[int] = None) -> bool:
    """
    Trigger an early log rotation when the active log exceeds a threshold.

    Args:
        force_threshold_bytes: Optional threshold override in bytes.

    Returns:
        ``True`` if rotation happened, otherwise ``False``.

    Raises:
        None.
    """
    threshold = _ROTATE_EARLY_BYTES if force_threshold_bytes is None else int(force_threshold_bytes)
    if get_log_size_bytes() <= threshold:
        return False
    logger = get_logger()
    for handler in logger.handlers:
        if isinstance(handler, RotatingFileHandler):
            try:
                handler.doRollover()
                _enforce_permissions(get_log_path())
                return True
            except Exception:
                return False
    return False
