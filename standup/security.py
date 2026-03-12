"""
security.py — API key validation, commit message redaction, and doctor health checks.
"""

import re
import stat
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    pass

console = Console()

# ---------------------------------------------------------------------------
# Precompiled redaction patterns
# ---------------------------------------------------------------------------

_PATTERNS = [
    # passwords / secrets in key=value style
    re.compile(
        r"(?i)(password|passwd|secret|token|api[_-]?key|access[_-]?key)"
        r"\s*[=:]\s*\S+",
        re.IGNORECASE,
    ),
    # IPv4 addresses (private ranges especially)
    re.compile(
        r"\b(?:10|172\.(?:1[6-9]|2\d|3[01])|192\.168)"
        r"\.\d{1,3}\.\d{1,3}\b"
    ),
    # private hostnames ending in .local or .internal
    re.compile(r"\b\w[\w.-]+\.(?:local|internal|corp|lan)\b", re.IGNORECASE),
    # bearer tokens
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*"),
]

_REDACTED = "[REDACTED]"

# ---------------------------------------------------------------------------
# API Key helpers (Groq only)
# ---------------------------------------------------------------------------


def validate_groq_api_key(key: str) -> bool:
    """Return True if the key looks like a valid Groq API key."""
    return isinstance(key, str) and key.startswith("gsk_") and len(key) >= 40


def mask_api_key(key: str) -> str:
    """Show first 10 and last 4 characters, mask the rest."""
    if not isinstance(key, str) or len(key) < 14:
        return "****"
    return key[:10] + ("*" * (len(key) - 14)) + key[-4:]


# ---------------------------------------------------------------------------
# Commit message redaction
# ---------------------------------------------------------------------------


def redact_sensitive_patterns(text: str) -> str:
    """Redact passwords, IPs, private hostnames from commit messages."""
    original = text
    for pattern in _PATTERNS:
        text = pattern.sub(_REDACTED, text)
    if text != original:
        console.print(
            "[yellow]⚠️  Sensitive patterns detected and redacted from commit messages.[/yellow]"
        )
    return text


# ---------------------------------------------------------------------------
# Config permission enforcement
# ---------------------------------------------------------------------------


def enforce_config_permissions(config_path: str) -> None:
    """Set config file to chmod 600 on Unix/macOS; warn on Windows."""
    p = Path(config_path)
    if not p.exists():
        return
    if sys.platform == "win32":
        console.print(
            "[yellow]⚠️  Windows detected: cannot enforce file permissions on "
            f"{config_path}. Ensure only your user can read it.[/yellow]"
        )
        return
    current = stat.S_IMODE(p.stat().st_mode)
    target = 0o600
    if current != target:
        p.chmod(target)


# ---------------------------------------------------------------------------
# Doctor command
# ---------------------------------------------------------------------------


def run_doctor() -> None:  # noqa: C901
    """Run security and health checks, print results as a rich table."""
    import importlib
    import os

    from standup.config import CONFIG_PATH, USAGE_PATH
    from standup.validator import validate_full_config
    from standup.security import validate_groq_api_key as _val_key

    checks: list = []  # list of (name, status, detail)

    def _ok(name: str, detail: str = "") -> None:
        checks.append((name, "✅", detail))

    def _fail(name: str, detail: str = "") -> None:
        checks.append((name, "❌", detail))

    def _warn(name: str, detail: str = "") -> None:
        checks.append((name, "⚠️", detail))

    # --- Load config ---
    config: dict = {}
    try:
        import json
        cfg_p = Path(CONFIG_PATH)
        if cfg_p.exists():
            config = json.loads(cfg_p.read_text())
    except Exception as exc:
        _fail("Config file", f"Could not load: {exc}")

    # 1. Provider configured
    provider_name = config.get("provider", {}).get("name", "")
    if provider_name in ("ollama", "groq"):
        _ok("Provider configured", f"provider.name = {provider_name!r}")
    else:
        _fail("Provider configured", f"provider.name is invalid: {provider_name!r}")

    # 2. Ollama availability
    if provider_name == "ollama":
        try:
            from standup.llm.ollama_provider import OllamaProvider
            p = OllamaProvider(config)
            if p.is_available():
                _ok("Ollama available", f"Model '{p.model}' is ready")
            else:
                _fail(
                    "Ollama available",
                    f"Server not running or model not pulled. Fix: ollama serve && ollama pull {p.model}",
                )
        except Exception as exc:
            _fail("Ollama available", str(exc))

    # 3. Groq key source
    if provider_name == "groq":
        env_key = os.environ.get("GROQ_API_KEY", "")
        cfg_key = config.get("provider", {}).get("groq", {}).get("api_key", "")
        if env_key:
            _ok("Groq key source", "Key loaded from environment variable GROQ_API_KEY ✅")
        elif cfg_key:
            _warn(
                "Groq key source",
                "Key is stored in config file — prefer GROQ_API_KEY env var for security.",
            )
        else:
            _fail("Groq key source", "No Groq API key found. Set GROQ_API_KEY env var.")

    # 4. Groq key format
    if provider_name == "groq":
        key = os.environ.get("GROQ_API_KEY") or config.get("provider", {}).get("groq", {}).get("api_key", "")
        if key and validate_groq_api_key(key):
            _ok("Groq key format", f"Key looks valid: {mask_api_key(key)}")
        elif key:
            _fail("Groq key format", "Key does not start with 'gsk_' or is too short.")
        else:
            _warn("Groq key format", "No key to validate.")

    # 5. Config file permissions
    cfg_p = Path(CONFIG_PATH)
    if cfg_p.exists():
        if sys.platform == "win32":
            _warn("Config file permissions", "Windows: cannot check permissions automatically.")
        else:
            mode = stat.S_IMODE(cfg_p.stat().st_mode)
            if mode == 0o600:
                _ok("Config file permissions", "chmod 600 ✅")
            else:
                _fail(
                    "Config file permissions",
                    f"Mode is {oct(mode)} — fix with: chmod 600 {CONFIG_PATH}",
                )
    else:
        _warn("Config file permissions", f"Config file not found at {CONFIG_PATH}")

    # 6. Config file not inside a git repo
    try:
        cfg_dir = cfg_p.parent.resolve()
        git_parent = cfg_dir / ".git"
        if git_parent.exists():
            _fail("Config file location", "Config file is inside a git repo! Move it to ~.")
        else:
            _ok("Config file location", f"{CONFIG_PATH} is not inside a git repo")
    except Exception:
        _warn("Config file location", "Could not determine config file location safety.")

    # 7. Usage file permissions
    usage_p = Path(USAGE_PATH)
    if usage_p.exists():
        if sys.platform == "win32":
            _warn("Usage file permissions", "Windows: cannot check permissions automatically.")
        else:
            mode = stat.S_IMODE(usage_p.stat().st_mode)
            if mode == 0o600:
                _ok("Usage file permissions", "chmod 600 ✅")
            else:
                _fail(
                    "Usage file permissions",
                    f"Mode is {oct(mode)} — fix with: chmod 600 {USAGE_PATH}",
                )
    else:
        _ok("Usage file permissions", "Usage file not yet created (normal on first run).")

    # 8. Repo paths valid
    repos = config.get("repos", [])
    if repos:
        from standup.validator import validate_repo_path
        all_ok = True
        for r in repos:
            ok, msg = validate_repo_path(r)
            if not ok:
                _fail("Repo paths valid", msg)
                all_ok = False
        if all_ok:
            _ok("Repo paths valid", f"{len(repos)} repo(s) configured and valid")
    else:
        _warn("Repo paths valid", "No repos configured. Run: standup --setup")

    # 9. Python version
    v = sys.version_info
    if v >= (3, 9):
        _ok("Python version", f"Python {v.major}.{v.minor}.{v.micro} >= 3.9 ✅")
    else:
        _fail("Python version", f"Python {v.major}.{v.minor} — requires 3.9+")

    # 10. Dependencies
    pkgs = ["ollama", "groq", "git", "pyperclip", "rich", "requests"]
    all_installed = True
    missing = []
    for pkg in pkgs:
        import_name = "git" if pkg == "git" else pkg
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(pkg)
            all_installed = False
    if all_installed:
        _ok("Dependencies", "All packages installed ✅")
    else:
        _fail("Dependencies", f"Missing: {', '.join(missing)} — run: pip install -r requirements.txt")

    # 11. Slack webhook
    webhook = config.get("slack_webhook_url", "")
    if webhook:
        from standup.validator import validate_slack_webhook
        ok, msg = validate_slack_webhook(webhook)
        if ok:
            _ok("Slack webhook", "Valid hooks.slack.com URL ✅")
        else:
            _fail("Slack webhook", msg)
    else:
        _ok("Slack webhook", "Not configured (optional)")

    # 12. Rate limit enabled
    rate = config.get("rate_limit", {})
    if isinstance(rate, dict) and rate.get("enabled") is True:
        _ok("Rate limit enabled", "enabled = true ✅")
    else:
        _warn("Rate limit enabled", "Rate limiting is disabled — consider enabling it.")

    # 13. Daily cap reasonable
    max_calls = rate.get("max_calls_per_day", 10) if isinstance(rate, dict) else 10
    try:
        m = int(max_calls)
        if 1 <= m <= 50:
            _ok("Daily cap reasonable", f"max_calls_per_day = {m}")
        else:
            _warn("Daily cap reasonable", f"max_calls_per_day = {m} is outside 1–50.")
    except (TypeError, ValueError):
        _fail("Daily cap reasonable", f"max_calls_per_day is not an integer: {max_calls!r}")

    # 14. Config fully valid
    ok, errors = validate_full_config(config)
    if ok:
        _ok("Config fully valid", "validate_full_config() passed ✅")
    else:
        for err in errors:
            _fail("Config fully valid", err)

    # --- Print table ---
    table = Table(title="StandupBot Doctor 🩺", show_lines=True)
    table.add_column("Check", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Detail")

    for name, status, detail in checks:
        table.add_row(name, status, detail)

    console.print(table)

    passed = sum(1 for _, s, _ in checks if s == "✅")
    warned = sum(1 for _, s, _ in checks if s == "⚠️")
    failed = sum(1 for _, s, _ in checks if s == "❌")
    total = len(checks)

    score = int(100 * (passed + 0.5 * warned) / total) if total else 0
    color = "green" if score >= 80 else "yellow" if score >= 60 else "red"
    console.print(
        f"\n[bold {color}]Health Score: {score}/100[/bold {color}] "
        f"  ✅ {passed}  ⚠️ {warned}  ❌ {failed}"
    )