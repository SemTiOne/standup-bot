"""
standup.security._redact - Secret masking, redaction, and error sanitizing.
"""

import json
import re
import sqlite3
from typing import Any

from rich.console import Console

from standup.logger import log_event

console = Console()


_REDACTED = "[REDACTED]"
_PATTERNS = [
    re.compile(
        r"(?i)(password|passwd|secret|token|api[_-]?key|access[_-]?key"
        r"|secret[_-]?key|private[_-]?key|auth[_-]?token)\s*[=:]\s*"
        r'(?:"[^"]*"|\'[^\']*\'|\S+)'
    ),
    re.compile(
        r"\b(?:10\.(?:25[0-5]|2[0-4]\d|1?\d{1,2})\.(?:25[0-5]|2[0-4]\d|1?\d{1,2})\.(?:25[0-5]|2[0-4]\d|1?\d{1,2})"
        r"|172\.(?:1[6-9]|2\d|3[01])\.(?:25[0-5]|2[0-4]\d|1?\d{1,2})\.(?:25[0-5]|2[0-4]\d|1?\d{1,2})"
        r"|192\.168\.(?:25[0-5]|2[0-4]\d|1?\d{1,2})\.(?:25[0-5]|2[0-4]\d|1?\d{1,2}))\b"
    ),
    re.compile(r"\b(?:fd[0-9a-f]{2}:|fc00:)[0-9a-fA-F:]+\b", re.IGNORECASE),
    re.compile(r"\b\w[\w.-]+\.(?:local|internal|corp|lan)\b", re.IGNORECASE),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*"),
]

# Type-tagged patterns for well-known secret formats that don't rely on a
# nearby trigger word (issue #2). Each is matched independently and replaced
# with a type-specific tag, e.g. "[REDACTED:GITHUB_TOKEN]", so the redaction
# reason stays visible without exposing the secret itself.
#
# The LLM key pattern's character class deliberately includes "-" and "_"
# (the base64url alphabet real provider keys use) with no upper length
# bound close to the prefix. An earlier draft used [A-Za-z0-9]{20,} with
# no "-"/"_", which stopped matching at the first hyphen in keys like
# "sk-ant-api03-..." and left the rest of a live key exposed in the
# "redacted" output.
_TAGGED_PATTERNS = [
    (
        "GITHUB_TOKEN",
        re.compile(r"\bghp_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    ),
    (
        "API_KEY",
        re.compile(r"\bsk-(?:ant-api03-|proj-)?[A-Za-z0-9_-]{20,}\b"),
    ),
    (
        "GROQ_KEY",
        re.compile(r"\bgsk_[A-Za-z0-9_-]{10,}\b"),
    ),
    (
        "AWS_KEY",
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ),
    (
        "SLACK_TOKEN",
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    ),
    (
        "URI_CREDENTIALS",
        # Matches the "user:password@" portion of a credentialed URI and
        # redacts only that segment, leaving scheme/host/path intact so the
        # rest of the commit message stays readable.
        re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s:@/]+:[^\s@/]+@"),
    ),
]
_ERROR_PATTERNS = [
    re.compile(r"[A-Za-z]:\\(?:[^\\/:*?\"<>|\r\n]+\\)*[^\\/:*?\"<>|\r\n]*"),
    re.compile(r"(?:/home/|/Users/)[^/\s]+(?:/[^\s]*)?"),
    re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+"),
    re.compile(r"gsk_[A-Za-z0-9_\-]{10,}"),
]


def validate_groq_api_key(key: str) -> bool:
    """
    Return whether a value looks like a valid Groq API key.

    Args:
        key: Candidate API key string.

    Returns:
        ``True`` if the format looks correct, otherwise ``False``.

    Raises:
        None.
    """
    return isinstance(key, str) and key.startswith("gsk_") and len(key) >= 40


def mask_api_key(key: str) -> str:
    """
    Mask an API key for safe display.

    Args:
        key: Raw API key.

    Returns:
        Masked representation suitable for terminal output.

    Raises:
        None.
    """
    if not isinstance(key, str) or len(key) < 14:
        return "****"
    return key[:10] + ("*" * (len(key) - 14)) + key[-4:]


def redact_sensitive_patterns(text: str) -> str:
    """
    Redact obvious secrets and internal network details from text.

    Args:
        text: Text to sanitize.

    Returns:
        Redacted text.

    Raises:
        None.
    """
    if not isinstance(text, str):
        text = str(text)
    original = text
    match_count = 0
    for pattern in _PATTERNS:
        matches = len(pattern.findall(text))
        if matches:
            match_count += matches
            text = pattern.sub(_REDACTED, text)
    for tag, pattern in _TAGGED_PATTERNS:
        matches = len(pattern.findall(text))
        if matches:
            match_count += matches
            text = pattern.sub(f"[REDACTED:{tag}]", text)
    if text != original:
        console.print(
            "[yellow][!]  Sensitive patterns detected and redacted from commit messages.[/yellow]"
        )
        log_event("redaction_fired", count=match_count)
    return text


def sanitize_error_message(exc: Any) -> str:
    """
    Produce a safe, user-friendly error message from an exception-like value.

    Args:
        exc: Exception instance or arbitrary value.

    Returns:
        Sanitized user-facing message no longer than 200 characters.

    Raises:
        None.
    """
    try:
        if exc is None:
            return "An unexpected error occurred."
        if isinstance(exc, FileNotFoundError):
            return "A required file or directory could not be found."
        if isinstance(exc, PermissionError):
            return "Permission was denied while accessing a required file or directory."
        if isinstance(exc, TimeoutError):
            return "The operation timed out."
        if isinstance(exc, json.JSONDecodeError):
            return "Invalid JSON content was encountered."
        if isinstance(exc, sqlite3.Error):
            return "The local history database could not be accessed safely."

        message = str(exc or "").strip()
        if not message:
            return "An unexpected error occurred."
        for pattern in _ERROR_PATTERNS:
            message = pattern.sub(_REDACTED, message)
        message = re.sub(r"\s+", " ", message).strip()
        if len(message) > 200:
            message = message[:200].rstrip() + "..."
        if not message:
            return "An unexpected error occurred."
        return message
    except Exception:
        return "An unexpected error occurred."
