"""
rate_limiter.py - Cooldown and daily usage cap tracking.

State is stored in ``~/.standup_usage.json`` and pruned to the most recent 30
days so unattended usage remains bounded.
"""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from rich.console import Console

from standup.logger import log_event
from standup.security import enforce_file_permissions

console = Console()

USAGE_PATH = str(Path.home() / ".standup_usage.json")
_HISTORY_DAYS = 30


def load_usage() -> dict:
    """
    Load usage state from disk.

    Args:
        None.

    Returns:
        Usage state dictionary.

    Raises:
        None.
    """
    path = Path(USAGE_PATH)
    if not path.exists():
        return {"last_call": None, "daily": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"last_call": None, "daily": {}}


def save_usage(usage: dict) -> None:
    """
    Persist usage state and prune old daily entries.

    Args:
        usage: Usage state dictionary to persist.

    Returns:
        None.

    Raises:
        None.
    """
    path = Path(USAGE_PATH)
    daily = usage.get("daily", {})
    cutoff = (date.today() - timedelta(days=_HISTORY_DAYS)).isoformat()
    usage["daily"] = {key: value for key, value in daily.items() if key >= cutoff}
    path.write_text(json.dumps(usage, indent=2), encoding="utf-8")
    enforce_file_permissions(str(path), label="Usage file")


def check_cooldown(usage: dict, cooldown_minutes: int) -> tuple[bool, int]:
    """
    Return whether cooldown allows another call and seconds remaining if blocked.

    Args:
        usage: Current usage state.
        cooldown_minutes: Configured cooldown period.

    Returns:
        Tuple of ``(allowed, seconds_remaining)``.

    Raises:
        None.
    """
    last_call = usage.get("last_call")
    if not last_call:
        return True, 0
    try:
        last_dt = datetime.fromisoformat(last_call)
    except (ValueError, TypeError):
        return True, 0

    elapsed = (datetime.now() - last_dt).total_seconds()
    required = cooldown_minutes * 60
    if elapsed >= required:
        return True, 0
    return False, int(required - elapsed)


def check_daily_cap(usage: dict, max_calls: int) -> tuple[bool, int]:
    """
    Return whether the caller is under the daily cap.

    Args:
        usage: Current usage state.
        max_calls: Maximum calls permitted per day.

    Returns:
        Tuple of ``(allowed, calls_used_today)``.

    Raises:
        None.
    """
    today = date.today().isoformat()
    calls_today = usage.get("daily", {}).get(today, 0)
    if calls_today < max_calls:
        return True, calls_today
    return False, calls_today


def record_call(usage: dict) -> dict:
    """
    Record a successful API call in the usage state.

    Args:
        usage: Existing usage state.

    Returns:
        Updated usage state.

    Raises:
        None.
    """
    usage["last_call"] = datetime.now().isoformat()
    today = date.today().isoformat()
    daily = usage.setdefault("daily", {})
    daily[today] = daily.get(today, 0) + 1
    return usage


def enforce_rate_limit(config: dict, force: bool = False) -> None:
    """
    Check cooldown and daily cap, exiting if limits are exceeded.

    Args:
        config: Loaded application config.
        force: Whether to bypass rate limits.

    Returns:
        None.

    Raises:
        SystemExit: If a limit is exceeded.
    """
    rate = config.get("rate_limit", {})
    if not isinstance(rate, dict) or not rate.get("enabled", True):
        return
    if force:
        console.print("[dim][!] Rate limit bypassed with --force[/dim]")
        return

    cooldown_minutes = int(rate.get("cooldown_minutes", 30))
    max_calls = int(rate.get("max_calls_per_day", 10))
    usage = load_usage()

    allowed, seconds_remaining = check_cooldown(usage, cooldown_minutes)
    if not allowed:
        log_event("rate_limit_hit", limit_type="cooldown", seconds_remaining=seconds_remaining)
        mins = seconds_remaining // 60
        secs = seconds_remaining % 60
        console.print(
            f"[yellow]⏳ Cooldown active. Please wait {mins}m {secs}s before running again.[/yellow]\n"
            "[dim]Use --force to bypass.[/dim]"
        )
        sys.exit(1)

    allowed, calls_today = check_daily_cap(usage, max_calls)
    if not allowed:
        log_event("rate_limit_hit", limit_type="daily", seconds_remaining=0)
        console.print(
            f"[yellow][x] Daily cap reached ({calls_today}/{max_calls} calls today).[/yellow]\n"
            "[dim]Use --force to bypass, or wait until tomorrow.[/dim]"
        )
        sys.exit(1)


def get_usage_report() -> str:
    """
    Return a seven-day usage summary with a simple unicode sparkline.

    Args:
        None.

    Returns:
        Multi-line usage report string.

    Raises:
        None.
    """
    usage = load_usage()
    daily = usage.get("daily", {})
    today = date.today()

    bars = "▁▂▃▄▅▆▇█"
    sparkline_days = []
    counts = []
    for i in range(6, -1, -1):
        current = (today - timedelta(days=i)).isoformat()
        count = daily.get(current, 0)
        counts.append(count)
        sparkline_days.append(current)

    max_count = max(counts) if any(counts) else 1
    spark = ""
    for count in counts:
        index = int((count / max_count) * (len(bars) - 1)) if max_count else 0
        spark += bars[index] if count > 0 else " "

    total_7 = sum(counts)
    total_all = sum(daily.values())
    last_call = usage.get("last_call", "Never")

    lines = [
        "📊 StandupBot Usage Report",
        "─" * 32,
        f"Last 7 days: [{spark}]",
    ]
    for index, day in enumerate(sparkline_days):
        lines.append(f"  {day}: {counts[index]} call(s)")
    lines += [
        "─" * 32,
        f"Total (7d): {total_7} calls",
        f"Total (all): {total_all} calls",
        f"Last call:   {last_call}",
    ]
    return "\n".join(lines)
