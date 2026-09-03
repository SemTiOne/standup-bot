"""
doctor.py - Security and health checks (extracted from security.py).

Run `standup doctor` to get a rich table with health score.
"""

import importlib
import json
import os
import stat
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()


def _permission_status(file_path: str, label: str) -> tuple[str, str, str]:
    path = Path(file_path)
    try:
        exists = path.exists()
    except OSError:
        return label, "❌", "Could not stat file."
    if not exists:
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
    from standup.security import (
        get_log_path,
        get_log_size_bytes,
        log_event,
        mask_api_key,
        sanitize_error_message,
        validate_groq_api_key,
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
        f"\n[bold {color}]Health Score: {score}/100[/bold {color}]  [+] {passed}  [!] {warned}  [x] {failed}"
    )
    log_event("doctor_run", health_score=score, passed=passed, warned=warned, failed=failed)
