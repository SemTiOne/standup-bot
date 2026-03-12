"""Tests for standup/rate_limiter.py."""

import json
from datetime import datetime, timedelta

import pytest

from standup.rate_limiter import (
    check_cooldown,
    check_daily_cap,
    get_usage_report,
    load_usage,
    record_call,
    save_usage,
)


# ---------------------------------------------------------------------------
# check_cooldown
# ---------------------------------------------------------------------------


def test_cooldown_no_last_call():
    usage = {"last_call": None, "daily": {}}
    allowed, remaining = check_cooldown(usage, 30)
    assert allowed is True
    assert remaining == 0


def test_cooldown_within_window():
    five_mins_ago = (datetime.now() - timedelta(minutes=5)).isoformat()
    usage = {"last_call": five_mins_ago, "daily": {}}
    allowed, remaining = check_cooldown(usage, 30)
    assert allowed is False
    assert remaining > 0


def test_cooldown_past_window():
    two_hours_ago = (datetime.now() - timedelta(hours=2)).isoformat()
    usage = {"last_call": two_hours_ago, "daily": {}}
    allowed, remaining = check_cooldown(usage, 30)
    assert allowed is True
    assert remaining == 0


def test_cooldown_zero_minutes():
    usage = {"last_call": datetime.now().isoformat(), "daily": {}}
    allowed, _ = check_cooldown(usage, 0)
    assert allowed is True


def test_cooldown_bad_timestamp():
    usage = {"last_call": "not-a-date", "daily": {}}
    allowed, remaining = check_cooldown(usage, 30)
    assert allowed is True


# ---------------------------------------------------------------------------
# check_daily_cap
# ---------------------------------------------------------------------------


def test_daily_cap_under():
    from datetime import date
    today = date.today().isoformat()
    usage = {"last_call": None, "daily": {today: 3}}
    allowed, used = check_daily_cap(usage, 10)
    assert allowed is True
    assert used == 3


def test_daily_cap_at_limit():
    from datetime import date
    today = date.today().isoformat()
    usage = {"last_call": None, "daily": {today: 10}}
    allowed, used = check_daily_cap(usage, 10)
    assert allowed is False
    assert used == 10


def test_daily_cap_no_calls_today():
    usage = {"last_call": None, "daily": {}}
    allowed, used = check_daily_cap(usage, 10)
    assert allowed is True
    assert used == 0


# ---------------------------------------------------------------------------
# record_call
# ---------------------------------------------------------------------------


def test_record_call_sets_last_call():
    usage = {"last_call": None, "daily": {}}
    updated = record_call(usage)
    assert updated["last_call"] is not None


def test_record_call_increments_daily():
    from datetime import date
    today = date.today().isoformat()
    usage = {"last_call": None, "daily": {today: 2}}
    updated = record_call(usage)
    assert updated["daily"][today] == 3


def test_record_call_first_call_of_day():
    usage = {"last_call": None, "daily": {}}
    updated = record_call(usage)
    from datetime import date
    today = date.today().isoformat()
    assert updated["daily"][today] == 1


# ---------------------------------------------------------------------------
# save_usage / load_usage
# ---------------------------------------------------------------------------


def test_save_and_load_usage(tmp_path, monkeypatch):
    from datetime import date
    path = str(tmp_path / ".standup_usage.json")
    monkeypatch.setattr("standup.rate_limiter.USAGE_PATH", path)

    today = date.today().isoformat()
    usage = {"last_call": f"{today}T10:00:00", "daily": {today: 3}}
    save_usage(usage)

    loaded = load_usage()
    assert loaded["daily"][today] == 3


def test_load_usage_missing_file(tmp_path, monkeypatch):
    path = str(tmp_path / ".standup_usage_missing.json")
    monkeypatch.setattr("standup.rate_limiter.USAGE_PATH", path)
    usage = load_usage()
    assert usage == {"last_call": None, "daily": {}}


def test_load_usage_invalid_json(tmp_path, monkeypatch):
    path = tmp_path / ".standup_usage_bad.json"
    path.write_text("{bad json}")
    monkeypatch.setattr("standup.rate_limiter.USAGE_PATH", str(path))
    usage = load_usage()
    assert usage == {"last_call": None, "daily": {}}


def test_save_usage_prunes_old_entries(tmp_path, monkeypatch):
    from datetime import date, timedelta
    path = str(tmp_path / ".standup_usage.json")
    monkeypatch.setattr("standup.rate_limiter.USAGE_PATH", path)

    old_date = (date.today() - timedelta(days=45)).isoformat()
    today = date.today().isoformat()
    usage = {"last_call": None, "daily": {old_date: 5, today: 2}}
    save_usage(usage)

    loaded = load_usage()
    assert old_date not in loaded["daily"]
    assert today in loaded["daily"]


# ---------------------------------------------------------------------------
# get_usage_report
# ---------------------------------------------------------------------------


def test_get_usage_report_returns_string(tmp_path, monkeypatch):
    path = str(tmp_path / ".standup_usage.json")
    monkeypatch.setattr("standup.rate_limiter.USAGE_PATH", path)
    report = get_usage_report()
    assert isinstance(report, str)
    assert "StandupBot Usage Report" in report


def test_get_usage_report_shows_7_days(tmp_path, monkeypatch):
    path = str(tmp_path / ".standup_usage.json")
    monkeypatch.setattr("standup.rate_limiter.USAGE_PATH", path)
    report = get_usage_report()
    # Should contain 7 date lines
    lines = [l for l in report.splitlines() if "202" in l and "call" in l]
    assert len(lines) == 7