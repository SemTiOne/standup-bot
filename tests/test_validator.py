"""Tests for standup/validator.py."""

import argparse
from typing import Tuple

import pytest

from standup.validator import (
    KNOWN_GROQ_MODELS,
    sanitize_path,
    sanitize_string,
    validate_author_email,
    validate_cli_args,
    validate_full_config,
    validate_hours_arg,
    validate_hours_lookback,
    validate_provider_arg,
    validate_provider_config,
    validate_rate_limit_config,
    validate_repo_path,
    validate_setup_input,
    validate_slack_webhook,
    validate_tone,
)


# ---------------------------------------------------------------------------
# validate_repo_path
# ---------------------------------------------------------------------------


def test_repo_path_empty():
    ok, _ = validate_repo_path("")
    assert not ok


def test_repo_path_nonexistent():
    ok, _ = validate_repo_path("/nonexistent/path/to/repo")
    assert not ok


def test_repo_path_relative():
    ok, _ = validate_repo_path("relative/path")
    assert not ok


def test_repo_path_not_git(tmp_path):
    ok, _ = validate_repo_path(str(tmp_path))
    assert not ok


def test_repo_path_valid(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    ok, msg = validate_repo_path(str(tmp_path))
    assert ok
    assert msg == ""


def test_repo_path_file_not_dir(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("hello")
    ok, _ = validate_repo_path(str(f))
    assert not ok


# ---------------------------------------------------------------------------
# validate_author_email
# ---------------------------------------------------------------------------


def test_email_empty_allowed():
    ok, _ = validate_author_email("")
    assert ok


def test_email_valid():
    ok, _ = validate_author_email("user@example.com")
    assert ok


def test_email_invalid():
    ok, _ = validate_author_email("notanemail")
    assert not ok


def test_email_no_tld():
    ok, _ = validate_author_email("user@domain")
    assert not ok


# ---------------------------------------------------------------------------
# validate_hours_lookback
# ---------------------------------------------------------------------------


def test_hours_valid():
    ok, _ = validate_hours_lookback(24)
    assert ok


def test_hours_string_coercible():
    ok, _ = validate_hours_lookback("48")
    assert ok


def test_hours_too_low():
    ok, _ = validate_hours_lookback(0)
    assert not ok


def test_hours_too_high():
    ok, _ = validate_hours_lookback(721)
    assert not ok


def test_hours_not_int():
    ok, _ = validate_hours_lookback("abc")
    assert not ok


# ---------------------------------------------------------------------------
# validate_tone
# ---------------------------------------------------------------------------


def test_tone_casual():
    ok, _ = validate_tone("casual")
    assert ok


def test_tone_formal():
    ok, _ = validate_tone("formal")
    assert ok


def test_tone_case_insensitive():
    ok, _ = validate_tone("CASUAL")
    assert ok


def test_tone_invalid():
    ok, _ = validate_tone("aggressive")
    assert not ok


# ---------------------------------------------------------------------------
# validate_slack_webhook
# ---------------------------------------------------------------------------


def test_slack_empty_allowed():
    ok, _ = validate_slack_webhook("")
    assert ok


def test_slack_valid():
    ok, _ = validate_slack_webhook("https://hooks.slack.com/services/abc/def")
    assert ok


def test_slack_invalid():
    ok, _ = validate_slack_webhook("https://example.com/webhook")
    assert not ok


# ---------------------------------------------------------------------------
# validate_rate_limit_config
# ---------------------------------------------------------------------------


def test_rate_limit_valid():
    cfg = {"enabled": True, "cooldown_minutes": 30, "max_calls_per_day": 10}
    ok, _ = validate_rate_limit_config(cfg)
    assert ok


def test_rate_limit_not_dict():
    ok, _ = validate_rate_limit_config("string")
    assert not ok


def test_rate_limit_bad_cooldown():
    cfg = {"enabled": True, "cooldown_minutes": -1, "max_calls_per_day": 10}
    ok, _ = validate_rate_limit_config(cfg)
    assert not ok


def test_rate_limit_bad_max_calls():
    cfg = {"enabled": True, "cooldown_minutes": 30, "max_calls_per_day": 100}
    ok, _ = validate_rate_limit_config(cfg)
    assert not ok


def test_rate_limit_missing_enabled():
    cfg = {"cooldown_minutes": 30, "max_calls_per_day": 10}
    ok, _ = validate_rate_limit_config(cfg)
    assert not ok


# ---------------------------------------------------------------------------
# validate_provider_config
# ---------------------------------------------------------------------------


def test_provider_config_valid_ollama():
    cfg = {
        "name": "ollama",
        "ollama": {"base_url": "http://localhost:11434", "model": "llama3"},
        "groq": {"api_key": "", "model": "llama-3.1-8b-instant"},
    }
    ok, msg = validate_provider_config(cfg)
    assert ok, msg


def test_provider_config_valid_groq():
    cfg = {
        "name": "groq",
        "ollama": {"base_url": "http://localhost:11434", "model": "llama3"},
        "groq": {"api_key": "", "model": "llama-3.1-8b-instant"},
    }
    ok, msg = validate_provider_config(cfg)
    assert ok, msg


def test_provider_config_unknown_name():
    cfg = {
        "name": "openai",
        "ollama": {"base_url": "http://localhost:11434", "model": "llama3"},
        "groq": {"api_key": "", "model": "llama-3.1-8b-instant"},
    }
    ok, _ = validate_provider_config(cfg)
    assert not ok


def test_provider_config_ollama_invalid_base_url():
    cfg = {
        "name": "ollama",
        "ollama": {"base_url": "not-a-url", "model": "llama3"},
        "groq": {"api_key": "", "model": "llama-3.1-8b-instant"},
    }
    ok, _ = validate_provider_config(cfg)
    assert not ok


def test_provider_config_ollama_empty_model():
    cfg = {
        "name": "ollama",
        "ollama": {"base_url": "http://localhost:11434", "model": ""},
        "groq": {"api_key": "", "model": "llama-3.1-8b-instant"},
    }
    ok, _ = validate_provider_config(cfg)
    assert not ok


def test_provider_config_groq_unknown_model():
    cfg = {
        "name": "groq",
        "ollama": {"base_url": "http://localhost:11434", "model": "llama3"},
        "groq": {"api_key": "", "model": "gpt-4"},
    }
    ok, _ = validate_provider_config(cfg)
    assert not ok


def test_provider_config_groq_empty_api_key_allowed():
    """Groq api_key can be empty in config (env var is allowed)."""
    cfg = {
        "name": "groq",
        "ollama": {"base_url": "http://localhost:11434", "model": "llama3"},
        "groq": {"api_key": "", "model": "llama-3.1-8b-instant"},
    }
    ok, msg = validate_provider_config(cfg)
    assert ok, msg


def test_provider_config_not_dict():
    ok, _ = validate_provider_config("string")
    assert not ok


# ---------------------------------------------------------------------------
# validate_provider_arg
# ---------------------------------------------------------------------------


def test_provider_arg_ollama():
    assert validate_provider_arg("ollama") == "ollama"


def test_provider_arg_groq():
    assert validate_provider_arg("groq") == "groq"


def test_provider_arg_invalid():
    with pytest.raises(argparse.ArgumentTypeError):
        validate_provider_arg("openai")


def test_provider_arg_case_insensitive():
    assert validate_provider_arg("OLLAMA") == "ollama"


# ---------------------------------------------------------------------------
# validate_hours_arg
# ---------------------------------------------------------------------------


def test_hours_arg_valid():
    assert validate_hours_arg("24") == 24


def test_hours_arg_invalid_string():
    with pytest.raises(argparse.ArgumentTypeError):
        validate_hours_arg("abc")


def test_hours_arg_out_of_range():
    with pytest.raises(argparse.ArgumentTypeError):
        validate_hours_arg("0")


# ---------------------------------------------------------------------------
# validate_cli_args
# ---------------------------------------------------------------------------


def test_cli_args_mutually_exclusive():
    ns = argparse.Namespace(hours=24, week=True, slack=False)
    errors = validate_cli_args(ns, {})
    assert any("mutually exclusive" in e for e in errors)


def test_cli_args_slack_no_webhook():
    ns = argparse.Namespace(hours=None, week=False, slack=True)
    errors = validate_cli_args(ns, {"slack_webhook_url": ""})
    assert any("slack_webhook_url" in e for e in errors)


def test_cli_args_slack_with_webhook():
    ns = argparse.Namespace(hours=None, week=False, slack=True)
    errors = validate_cli_args(ns, {"slack_webhook_url": "https://hooks.slack.com/x"})
    assert errors == []


def test_cli_args_valid():
    ns = argparse.Namespace(hours=24, week=False, slack=False)
    errors = validate_cli_args(ns, {})
    assert errors == []


# ---------------------------------------------------------------------------
# validate_full_config
# ---------------------------------------------------------------------------


def _make_valid_config(tmp_path) -> dict:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    return {
        "repos": [str(tmp_path)],
        "author_email": "",
        "hours_lookback": 24,
        "tone": "casual",
        "slack_webhook_url": "",
        "provider": {
            "name": "ollama",
            "ollama": {"base_url": "http://localhost:11434", "model": "llama3"},
            "groq": {"api_key": "", "model": "llama-3.1-8b-instant"},
        },
        "rate_limit": {"cooldown_minutes": 30, "max_calls_per_day": 10, "enabled": True},
    }


def test_full_config_valid(tmp_path):
    config = _make_valid_config(tmp_path)
    ok, errors = validate_full_config(config)
    assert ok, errors


def test_full_config_multiple_errors():
    config = {
        "repos": "not-a-list",
        "author_email": "bad",
        "hours_lookback": 9999,
        "tone": "angry",
        "slack_webhook_url": "http://wrong.com",
        "provider": {"name": "bad"},
        "rate_limit": {"enabled": "yes", "cooldown_minutes": -1, "max_calls_per_day": 100},
    }
    ok, errors = validate_full_config(config)
    assert not ok
    assert len(errors) >= 4


# ---------------------------------------------------------------------------
# validate_setup_input
# ---------------------------------------------------------------------------


def test_setup_input_unknown_field():
    ok, _ = validate_setup_input("nonexistent_field", "value")
    assert not ok


def test_setup_input_tone():
    ok, _ = validate_setup_input("tone", "casual")
    assert ok


def test_setup_input_groq_model_valid():
    ok, _ = validate_setup_input("groq_model", "llama-3.1-8b-instant")
    assert ok


def test_setup_input_groq_model_invalid():
    ok, _ = validate_setup_input("groq_model", "gpt-9")
    assert not ok


# ---------------------------------------------------------------------------
# sanitize_string / sanitize_path
# ---------------------------------------------------------------------------


def test_sanitize_string_strips():
    assert sanitize_string("  hello  ") == "hello"


def test_sanitize_string_removes_nulls():
    assert "\x00" not in sanitize_string("a\x00b")


def test_sanitize_string_truncates():
    assert len(sanitize_string("x" * 1000, max_length=10)) == 10


def test_sanitize_path_expands_tilde(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    result = sanitize_path("~/foo")
    assert result.startswith(str(tmp_path))