"""
security.py - API key masking, redaction, file permissions, and doctor checks.
"""

import importlib
import json
import os
import re
import sqlite3
import stat
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from standup.logger import get_log_path, get_log_size_bytes, log_event

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
        r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
        r"|192\.168\.\d{1,3}\.\d{1,3})\b"
    ),
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

_ALL_SECRET_PATTERNS = (
    [(tag, pat) for tag, pat in _TAGGED_PATTERNS]
    + [("TRIGGER_SECRET", pat) for pat in _PATTERNS[:1]]
    + [("GROQ_KEY", re.compile(r"gsk_[A-Za-z0-9_\-]{10,}"))]
)


def _detect_secrets(text: str) -> list[str]:
    """Return a list of secret-type tags found in *text*."""
    found: list[str] = []
    for tag, pattern in _ALL_SECRET_PATTERNS:
        if pattern.search(text):
            found.append(tag)
    return found


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
            "[yellow]⚠️  Sensitive patterns detected and redacted from commit messages.[/yellow]"
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
                f"[yellow]⚠️  No OS keychain available for {key_name}; "
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
    if not path.exists():
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
            f"[yellow]⚠️  Could not restrict permissions on {label} via icacls. "
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

    Any secrets detected in *content* via ``_detect_secrets`` are
    automatically scrubbed (replaced with ``[REDACTED:<TAG>]``)
    before the write, so clear-text secrets never land on disk.

    Args:
        file_path: Path to write to.
        content: Text content to write.
        label: Human-friendly file label for warnings.

    Returns:
        None.
    """
    secrets = _detect_secrets(content)
    if secrets:
        content = redact_sensitive_patterns(content)
        console.print(
            f"[yellow]⚠️  Secrets detected in {label} before write; "
            f"scrubbed ({', '.join(secrets)}).[/yellow]"
        )
        log_event("write_scrubbed_secrets", tags=secrets, path=file_path)
    path = Path(file_path)
    path.touch(exist_ok=True)
    enforce_file_permissions(file_path, label=label)
    path.write_text(content, encoding="utf-8")


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


def _permission_status(file_path: str, label: str) -> tuple[str, str, str]:
    path = Path(file_path)
    if not path.exists():
        return label, "ℹ️", "Not yet created."
    if sys.platform == "win32":
        return label, "⚠️", "Windows: cannot verify permissions automatically."
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return label, "❌", "Could not stat file."
    if mode == 0o600:
        return label, "✅", "chmod 600 OK"
    return label, "❌", f"Mode is {oct(mode)}; expected 0o600"


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024.0:.1f} KB"
    return f"{size_bytes / float(1024 * 1024):.2f} MB"


def run_doctor() -> None:  # noqa: C901
    """
    Run security and health checks and print a rich table.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    import os

    from standup.config import CONFIG_PATH, USAGE_PATH
    from standup.history import (
        _MIGRATIONS,
        _get_connection,
        get_current_schema_version,
        get_db_path,
        get_db_size_bytes,
        get_row_count,
        init_db,
    )
    from standup.validator import (
        validate_full_config,
        validate_quality_config,
        validate_repo_path,
        validate_slack_webhook,
        validate_template_name,
    )

    checks: list[tuple[str, str, str]] = []

    def _record(name: str, status: str, detail: str) -> None:
        checks.append((name, status, detail))

    config = {}
    config_path = Path(CONFIG_PATH)
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            _record("Config file", "❌", sanitize_error_message(exc))
    else:
        _record("Config file", "⚠️", "Config file not found. Run: standup --setup")

    provider_name = config.get("provider", {}).get("name", "")
    if provider_name in ("ollama", "groq"):
        _record("Provider configured", "✅", f"provider.name = {provider_name!r}")
    else:
        _record("Provider configured", "❌", "provider.name is missing or invalid.")

    if provider_name == "ollama":
        try:
            from standup.llm.ollama_provider import OllamaProvider

            provider = OllamaProvider(config)
            if provider.is_available():
                _record("Ollama available", "✅", "Configured model is reachable.")
            else:
                _record("Ollama available", "❌", "Server not running or configured model missing.")
        except Exception as exc:
            _record("Ollama available", "❌", sanitize_error_message(exc))

    if provider_name == "groq":
        env_key = os.environ.get("GROQ_API_KEY", "")
        cfg_key = config.get("provider", {}).get("groq", {}).get("api_key", "")
        if env_key:
            _record("Groq key source", "✅", "Loaded from GROQ_API_KEY")
        elif cfg_key:
            _record("Groq key source", "⚠️", "Stored in config file; prefer GROQ_API_KEY env var.")
        else:
            _record("Groq key source", "❌", "No Groq API key found.")

        key = env_key or cfg_key
        if key and validate_groq_api_key(key):
            _record("Groq key format", "✅", f"Key looks valid: {mask_api_key(key)}")
        elif key:
            _record("Groq key format", "❌", "Key format is invalid.")
        else:
            _record("Groq key format", "⚠️", "No key to validate.")

    for name, path in (
        ("Config file permissions", CONFIG_PATH),
        ("Usage file permissions", USAGE_PATH),
        ("History DB permissions", get_db_path()),
        ("Log file permissions", get_log_path()),
    ):
        _record(*_permission_status(path, name))

    log_path = Path(get_log_path())
    if log_path.exists():
        _record("Log file", "✅", f"{log_path} ({_format_size(get_log_size_bytes())})")
    else:
        _record("Log file", "ℹ️", "No log file yet.")

    try:
        cfg_dir = config_path.parent.resolve()
        if (cfg_dir / ".git").exists():
            _record("Config file location", "❌", "Config file appears to be inside a git repo.")
        else:
            _record("Config file location", "✅", "Config file is outside the workspace git repo.")
    except Exception as exc:
        _record("Config file location", "⚠️", sanitize_error_message(exc))

    repos = config.get("repos", [])
    if repos:
        repo_errors = []
        for repo in repos:
            ok, message = validate_repo_path(repo)
            if not ok:
                repo_errors.append(message)
        if repo_errors:
            _record("Repo paths valid", "❌", " | ".join(repo_errors))
        else:
            _record("Repo paths valid", "✅", f"{len(repos)} repo(s) configured and valid")
    else:
        _record("Repo paths valid", "⚠️", "No repos configured.")

    version_info = sys.version_info
    if version_info >= (3, 10):
        _record(
            "Python version",
            "✅",
            f"Python {version_info.major}.{version_info.minor}.{version_info.micro} >= 3.10",
        )
    else:
        _record(
            "Python version",
            "❌",
            f"Python {version_info.major}.{version_info.minor} detected; requires 3.10+",
        )

    missing_dependencies = []
    for package_name in ("ollama", "groq", "git", "pyperclip", "rich", "requests"):
        import_name = "git" if package_name == "git" else package_name
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing_dependencies.append(package_name)
    if missing_dependencies:
        _record(
            "Dependencies",
            "❌",
            f"Missing: {', '.join(missing_dependencies)} - run: pip install -r requirements.txt",
        )
    else:
        _record("Dependencies", "✅", "All required packages are installed.")

    webhook = config.get("slack_webhook_url", "")
    if webhook:
        ok, message = validate_slack_webhook(webhook)
        _record("Slack webhook", "✅" if ok else "❌", message or "Valid hooks.slack.com URL")
    else:
        _record("Slack webhook", "ℹ️", "Not configured (optional).")

    quality_ok, quality_msg = validate_quality_config(config.get("quality", {}))
    _record(
        "Quality config",
        "✅" if quality_ok else "❌",
        quality_msg or "Quality scoring configuration is valid.",
    )

    template_ok, template_msg = validate_template_name(
        config.get("template", "default"),
        config.get("custom_templates", {}),
    )
    _record(
        "Template config",
        "✅" if template_ok else "❌",
        template_msg or "Selected template is valid.",
    )

    rate_limit = config.get("rate_limit", {})
    if isinstance(rate_limit, dict) and rate_limit.get("enabled") is True:
        _record("Rate limit enabled", "✅", "enabled = true")
    else:
        _record("Rate limit enabled", "⚠️", "Rate limiting is disabled.")

    ok, errors = validate_full_config(config)
    if ok:
        _record("Config fully valid", "✅", "validate_full_config() passed")
    else:
        for error in errors:
            _record("Config fully valid", "❌", error)
        log_event("config_validation_failed", error_count=len(errors))

    try:
        init_db()
        db_path = get_db_path()
        db_size = get_db_size_bytes(db_path)
        row_count = get_row_count(db_path)
        if db_size > 20 * 1024 * 1024:
            _record("History DB size", "❌", _format_size(db_size))
        elif db_size > 5 * 1024 * 1024:
            _record("History DB size", "⚠️", _format_size(db_size))
        else:
            _record("History DB size", "✅", _format_size(db_size))
        _record("History DB rows", "✅", str(row_count))
        with _get_connection(db_path) as conn:
            journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            schema_version = get_current_schema_version(conn)
        latest_version = max(version for version, _, _ in _MIGRATIONS)
        _record(
            "History DB schema",
            "✅" if schema_version == latest_version else "⚠️",
            f"{schema_version}/{latest_version}",
        )
        _record(
            "History DB WAL mode",
            "✅" if str(journal_mode).lower() == "wal" else "⚠️",
            str(journal_mode),
        )
    except Exception as exc:
        _record("History DB", "❌", sanitize_error_message(exc))

    table = Table(title="StandupBot Doctor", show_lines=True)
    table.add_column("Check", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Detail")

    for name, status, detail in checks:
        table.add_row(name, status, detail)

    console.print(table)

    passed = sum(1 for _, status, _ in checks if status == "✅")
    warned = sum(1 for _, status, _ in checks if status in ("⚠️", "ℹ️"))
    failed = sum(1 for _, status, _ in checks if status == "❌")
    total = len(checks)
    score = int(100 * (passed + 0.5 * warned) / total) if total else 0
    color = "green" if score >= 80 else "yellow" if score >= 60 else "red"
    console.print(
        f"\n[bold {color}]Health Score: {score}/100[/bold {color}]  ✅ {passed}  ⚠️ {warned}  ❌ {failed}"
    )
    log_event("doctor_run", health_score=score, passed=passed, warned=warned, failed=failed)
