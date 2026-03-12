"""
rate_limiter.py — Cooldown and daily usage cap tracking.

State stored in ~/.standup_usage.json (chmod 600).
Keeps 30 days of history.
"""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Tuple

from rich.console import Console

console = Console()

USAGE_PATH = str(Path.home() / ".standup_usage.json")
_HISTORY_DAYS = 30


# ---------------------------------------------------------------------------
# Load / Save
# ---------------------------------------------------------------------------


def load_usage() -> dict:
    """Load usage state from ~/.standup_usage.json."""
    p = Path(USAGE_PATH)
    if not p.exists():
        return {"last_call": None, "daily": {}}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {"last_call": None, "daily": {}}


def save_usage(usage: dict) -> None:
    """Persist usage state and set chmod 600."""
    p = Path(USAGE_PATH)
    # Prune old entries (>30 days)
    daily = usage.get("daily", {})
    cutoff = (date.today() - timedelta(days=_HISTORY_DAYS)).isoformat()
    usage["daily"] = {k: v for k, v in daily.items() if k >= cutoff}

    p.write_text(json.dumps(usage, indent=2))
    if sys.platform != "win32":
        p.chmod(0o600)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_cooldown(usage: dict, cooldown_minutes: int) -> Tuple[bool, int]:
    """
    Return (allowed, seconds_remaining).
    allowed=True means OK to proceed.
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
    remaining = int(required - elapsed)
    return False, remaining


def check_daily_cap(usage: dict, max_calls: int) -> Tuple[bool, int]:
    """
    Return (allowed, calls_used_today).
    allowed=True means under the cap.
    """
    today = date.today().isoformat()
    calls_today = usage.get("daily", {}).get(today, 0)
    if calls_today < max_calls:
        return True, calls_today
    return False, calls_today


def record_call(usage: dict) -> dict:
    """Record a call and return updated usage dict."""
    now = datetime.now().isoformat()
    usage["last_call"] = now
    today = date.today().isoformat()
    daily = usage.setdefault("daily", {})
    daily[today] = daily.get(today, 0) + 1
    return usage


# ---------------------------------------------------------------------------
# Enforce
# ---------------------------------------------------------------------------


def enforce_rate_limit(config: dict, force: bool = False) -> None:
    """
    Check cooldown and daily cap. Exit with message if limits exceeded.
    --force bypasses both limits.
    """
    rate = config.get("rate_limit", {})
    if not isinstance(rate, dict) or not rate.get("enabled", True):
        return
    if force:
        console.print("[dim]⚡ Rate limit bypassed with --force[/dim]")
        return

    cooldown_minutes = int(rate.get("cooldown_minutes", 30))
    max_calls = int(rate.get("max_calls_per_day", 10))

    usage = load_usage()

    allowed, seconds_remaining = check_cooldown(usage, cooldown_minutes)
    if not allowed:
        mins = seconds_remaining // 60
        secs = seconds_remaining % 60
        console.print(
            f"[yellow]⏳ Cooldown active. Please wait {mins}m {secs}s before running again.[/yellow]\n"
            "[dim]Use --force to bypass.[/dim]"
        )
        sys.exit(1)

    allowed, calls_today = check_daily_cap(usage, max_calls)
    if not allowed:
        console.print(
            f"[yellow]🚫 Daily cap reached ({calls_today}/{max_calls} calls today).[/yellow]\n"
            "[dim]Use --force to bypass, or wait until tomorrow.[/dim]"
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Usage report
# ---------------------------------------------------------------------------


def get_usage_report() -> str:
    """Return a 7-day usage summary with a unicode sparkline."""
    usage = load_usage()
    daily = usage.get("daily", {})
    today = date.today()

    bars = "▁▂▃▄▅▆▇█"
    sparkline_days = []
    counts = []
    for i in range(6, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        count = daily.get(d, 0)
        counts.append(count)
        sparkline_days.append(d)

    max_count = max(counts) if any(counts) else 1
    spark = ""
    for c in counts:
        idx = int((c / max_count) * (len(bars) - 1)) if max_count else 0
        spark += bars[idx] if c > 0 else " "

    total_7 = sum(counts)
    total_all = sum(daily.values())
    last_call = usage.get("last_call", "Never")

    lines = [
        "📊 StandupBot Usage Report",
        "─" * 32,
        f"Last 7 days: [{spark}]",
    ]
    for i, d in enumerate(sparkline_days):
        lines.append(f"  {d}: {counts[i]} call(s)")
    lines += [
        "─" * 32,
        f"Total (7d): {total_7} calls",
        f"Total (all): {total_all} calls",
        f"Last call:   {last_call}",
    ]
    return "\n".join(lines)