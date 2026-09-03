"""
security.py - API key masking, redaction, file permissions, and doctor checks.
"""

import contextlib
import json
import os
import re
import sqlite3
import stat
import sys
from pathlib import Path
from typing import Any

from rich.console import Console

from standup.logger import get_log_path, get_log_size_bytes, log_event  # noqa: F401

_PERMISSION_WARNED_PATHS: set = set()

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


_KEYRING_SERVICE = "standup-bot"
_KEYRING_WARNED_KEYS: set = set()


def store_secret(key_name: str, value: str) -> bool:
    """
    Store a secret in the OS keychain (Keychain on macOS, Credential
    Manager on Windows, Secret Service on Linux) via ``keyring``.

    Returns:
        True if the secret was stored in the OS keychain. False if no
        keychain backend is available (common in headless Linux, CI,
        and Docker environments) or the backend raised any other
        error; callers should fall back to their own storage in
        that case rather than lose the value. Warns once per key,
        not on every call, to avoid spamming a CLI tool's output.
    """
    if not value:
        return False
    try:
        import keyring

        keyring.set_password(_KEYRING_SERVICE, key_name, value)
        return True
    except Exception:
        if key_name not in _KEYRING_WARNED_KEYS:
            _KEYRING_WARNED_KEYS.add(key_name)
            console.print(
                f"[yellow][!]  No OS keychain available for {key_name}; "
                "storing it in the config file instead (permissions "
                "still restricted to your user).[/yellow]"
            )
        return False


def get_secret(key_name: str) -> str | None:
    """
    Retrieve a secret previously stored via ``store_secret``.

    Returns:
        The stored value, or ``None`` if it isn't in the OS keychain
        (never stored there, or no backend available); callers
        should fall back to a config-file value in that case.
    """
    try:
        import keyring

        return keyring.get_password(_KEYRING_SERVICE, key_name)
    except Exception:
        return None


def delete_secret(key_name: str) -> None:
    """Best-effort delete of a secret from the OS keychain. Never raises."""
    try:
        import keyring

        keyring.delete_password(_KEYRING_SERVICE, key_name)
    except Exception:  # noqa: S110 – intentionally swallowed; best-effort delete
        pass


def enforce_file_permissions(file_path: str, label: str = "File") -> None:
    """
    Restrict a file to the current user only: chmod 600 on Unix/macOS,
    an icacls ACL reset on Windows.

    Args:
        file_path: Path to the file.
        label: Human-friendly file label for warnings.

    Returns:
        None.

    Raises:
        None.
    """
    path = Path(file_path)
    try:
        if not path.exists():
            return
    except OSError:
        return
    if sys.platform == "win32":
        _enforce_windows_acl(file_path, label)
        return
    try:
        current = stat.S_IMODE(path.stat().st_mode)
        if current != 0o600:
            path.chmod(0o600)
    except OSError:
        return


def _enforce_windows_acl(file_path: str, label: str = "File") -> None:
    """
    Restrict a file to the current user on Windows using ``icacls``:
    strip inherited permissions and grant full control to the owner
    only. Falls back to a one-time warning if ``icacls`` itself is
    unavailable or fails (e.g. on a filesystem that doesn't support
    ACLs), rather than silently claiming the file is protected.
    """
    import subprocess

    try:
        result = subprocess.run(
            [
                "icacls",
                file_path,
                "/inheritance:r",
                "/grant:r",
                f"{os.environ.get('USERNAME', '')}:F",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return
    except (OSError, subprocess.SubprocessError):
        pass

    if file_path not in _PERMISSION_WARNED_PATHS:
        _PERMISSION_WARNED_PATHS.add(file_path)
        console.print(
            f"[yellow][!]  Could not restrict permissions on {label} via icacls. "
            "Ensure only your user can read it.[/yellow]"
        )


def write_text_restricted(file_path: str, content: str, label: str = "File") -> None:
    """
    Write ``content`` to ``file_path`` such that the file never has
    broader-than-owner-only permissions, including the moment it is
    first created.

    ``Path.write_text()`` creates the file with the OS's default mode
    (commonly 644; world-readable) and only becomes owner-only after
    a subsequent, separate ``enforce_file_permissions()`` call, a
    window in which sensitive content (API keys, webhook URLs) sits
    world-readable on disk. This creates the file empty first (with
    permissions locked down immediately after creation, before any
    content exists), then writes the real content, closing that
    window.

    Deliberately does NOT scan or scrub content for secrets: this is
    a generic write primitive and cannot know whether a given caller's
    secret-shaped content is an accidental leak or an intentional,
    already-considered persistence decision (e.g. save_config()'s
    documented OS-keychain-first, permission-restricted-file-fallback
    design). An earlier version of this function auto-redacted
    detected secrets, which (a) was silently non-functional for Groq
    keys specifically; see the GROQ_KEY note on _TAGGED_PATTERNS;
    and (b) would, if made to actually work, silently corrupt
    save_config()'s fallback value on every save in environments
    without a keychain (headless Linux, CI, Docker), since it can't
    distinguish that case from an accidental leak. Secret redaction
    belongs at the call site, where intent is known; see
    redact_sensitive_patterns() for callers (e.g. commit message
    formatting) that do want it.

    Args:
        file_path: Path to write to.
        content: Text content to write.
        label: Human-friendly file label for warnings.

    Returns:
        None.
    """
    path = Path(file_path)
    path.touch(exist_ok=True)
    enforce_file_permissions(file_path, label=label)

    from cryptography.fernet import Fernet

    key_path = Path(str(path) + ".key")
    if not key_path.exists():
        key = Fernet.generate_key()
        key_path.write_bytes(key)
        enforce_file_permissions(str(key_path), label=f"{label} encryption key")
    else:
        key = key_path.read_bytes()

    encrypted = Fernet(key).encrypt(content.encode("utf-8"))
    path.write_bytes(encrypted)


def read_text_restricted(file_path: str, label: str = "File") -> str:
    """Read and decrypt a file written by write_text_restricted.

    Falls back to plain text if no encryption key is found, preserving
    backward compatibility with files written before encryption was added.
    """
    path = Path(file_path)
    data = path.read_bytes()
    key_path = Path(str(path) + ".key")
    if key_path.exists():
        try:
            from cryptography.fernet import Fernet

            key = key_path.read_bytes()
            return Fernet(key).decrypt(data).decode("utf-8")
        except Exception:  # noqa: S110
            pass
    return data.decode("utf-8")


def enforce_config_permissions(config_path: str) -> None:
    """
    Backward-compatible wrapper for config permission enforcement.

    Args:
        config_path: Config file path.

    Returns:
        None.

    Raises:
        None.
    """
    enforce_file_permissions(config_path, label="Config file")


# Re-export doctor helpers for backward compat (moved to standup.doctor)
# Kept here so `from standup.security import run_doctor` still works.
with contextlib.suppress(ImportError):  # pragma: no cover
    from standup.doctor import _format_size, _permission_status, run_doctor  # noqa: F401
