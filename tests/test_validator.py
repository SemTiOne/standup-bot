"""Tests for standup/validator.py."""

import argparse
import os
from pathlib import Path

import pytest

from standup.validator import (
    KNOWN_GROQ_MODELS,
    parse_bool_text,
    sanitize_path,
    sanitize_string,
    validate_author_email,
    validate_boolean,
    validate_cli_args,
    validate_custom_templates_config,
    validate_full_config,
    validate_hours_arg,
    validate_hours_lookback,
    validate_path_safety,
    validate_positive_int_arg,
    validate_provider_arg,
    validate_provider_config,
    validate_quality_config,
    validate_rate_limit_config,
    validate_repo_path,
    validate_resource_limits,
    validate_setup_input,
    validate_slack_webhook,
    validate_template_name,
    validate_template_string,
    validate_tone,
)


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
    (tmp_path / ".git").mkdir()
    ok, msg = validate_repo_path(str(tmp_path))
    assert ok
    assert msg == ""


def test_repo_path_file_not_dir(tmp_path):
    file_path = tmp_path / "file.txt"
    file_path.write_text("hello", encoding="utf-8")
    ok, _ = validate_repo_path(str(file_path))
    assert not ok


def test_validate_path_safety_rejects_null_bytes():
    ok, _ = validate_path_safety("bad\x00path")
    assert not ok


def test_validate_path_safety_rejects_network_path():
    ok, _ = validate_path_safety("//server/share")
    assert not ok


def test_validate_path_safety_rejects_too_long_path():
    ok, _ = validate_path_safety("/" + ("a" * 5000))
    assert not ok


def test_validate_path_safety_accepts_absolute_path(tmp_path):
    ok, _ = validate_path_safety(str(tmp_path))
    assert ok


@pytest.mark.skipif(os.name == "nt", reason="Symlink traversal check is Unix-only")
def test_validate_path_safety_rejects_symlink_outside_parent(tmp_path):
    outside = tmp_path.parent / "outside-target"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "repo-link"
    os.symlink(str(outside), str(link))
    ok, _ = validate_path_safety(str(link))
    assert not ok


def test_email_empty_allowed():
    ok, _ = validate_author_email("")
    assert ok


def test_email_valid():
    ok, _ = validate_author_email("user@example.com")
    assert ok


def test_email_invalid():
    ok, _ = validate_author_email("notanemail")
    assert not ok


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


def test_tone_casual():
    ok, _ = validate_tone("casual")
    assert ok


def test_tone_formal():
    ok, _ = validate_tone("formal")
    assert ok


def test_tone_invalid():
    ok, _ = validate_tone("aggressive")
    assert not ok


def test_slack_empty_allowed():
    ok, _ = validate_slack_webhook("")
    assert ok


def test_slack_valid():
    ok, _ = validate_slack_webhook("https://hooks.slack.com/services/abc/def")
    assert ok


def test_slack_invalid():
    ok, _ = validate_slack_webhook("https://example.com/webhook")
    assert not ok


def test_rate_limit_valid():
    cfg = {"enabled": True, "cooldown_minutes": 30, "max_calls_per_day": 10}
    ok, _ = validate_rate_limit_config(cfg)
    assert ok


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


def test_provider_config_groq_accepts_unlisted_model():
    """KNOWN_GROQ_MODELS is for display only; any non-empty string is valid."""
    cfg = {
        "name": "groq",
        "ollama": {"base_url": "http://localhost:11434", "model": "llama3"},
        "groq": {"api_key": "", "model": "some-future-model-id"},
    }
    ok, _ = validate_provider_config(cfg)
    assert ok


def test_provider_config_groq_rejects_empty_model():
    cfg = {
        "name": "groq",
        "ollama": {"base_url": "http://localhost:11434", "model": "llama3"},
        "groq": {"api_key": "", "model": ""},
    }
    ok, _ = validate_provider_config(cfg)
    assert not ok


def test_provider_arg_ollama():
    assert validate_provider_arg("ollama") == "ollama"


def test_provider_arg_invalid():
    with pytest.raises(argparse.ArgumentTypeError):
        validate_provider_arg("openai")


def test_hours_arg_valid():
    assert validate_hours_arg("24") == 24


def test_hours_arg_invalid_string():
    with pytest.raises(argparse.ArgumentTypeError):
        validate_hours_arg("abc")


def test_cli_args_mutually_exclusive():
    ns = argparse.Namespace(hours=24, week=True, slack=False)
    errors = validate_cli_args(ns, {})
    assert any("mutually exclusive" in error for error in errors)


def test_cli_args_slack_no_webhook():
    ns = argparse.Namespace(hours=None, week=False, slack=True)
    errors = validate_cli_args(ns, {"slack_webhook_url": ""})
    assert any("slack_webhook_url" in error for error in errors)


def _make_valid_config(tmp_path) -> dict:
    (tmp_path / ".git").mkdir()
    return {
        "repos": [str(tmp_path)],
        "author_email": "",
        "hours_lookback": 24,
        "tone": "casual",
        "slack_webhook_url": "",
        "provider": {
            "name": "ollama",
            "ollama": {"base_url": "http://localhost:11434", "model": "llama3"},
            "groq": {"api_key": "", "model": KNOWN_GROQ_MODELS[0]},
        },
        "rate_limit": {"cooldown_minutes": 30, "max_calls_per_day": 10, "enabled": True},
        "quality": {"enabled": True, "min_score": 0, "show_breakdown": False},
        "noise_filter_enabled": True,
        "template": "default",
        "custom_templates": {},
        "auto_warm_up": False,
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


def test_validate_resource_limits_rejects_too_many_repos(tmp_path):
    config = _make_valid_config(tmp_path)
    config["repos"] = [str(tmp_path)] * 25
    ok, errors = validate_resource_limits(config)
    assert not ok
    assert errors


def test_validate_resource_limits_rejects_too_many_custom_templates(tmp_path):
    config = _make_valid_config(tmp_path)
    config["custom_templates"] = {f"t{i}": "Done: {yesterday}" for i in range(11)}
    ok, errors = validate_resource_limits(config)
    assert not ok
    assert errors


def test_setup_input_unknown_field():
    ok, _ = validate_setup_input("nonexistent_field", "value")
    assert not ok


def test_setup_input_tone():
    ok, _ = validate_setup_input("tone", "casual")
    assert ok


def test_setup_input_groq_model_known():
    ok, _ = validate_setup_input("groq_model", "llama-3.1-8b-instant")
    assert ok


def test_setup_input_groq_model_unlisted_accepted():
    """Unknown model IDs are accepted so users are not blocked by a stale list."""
    ok, _ = validate_setup_input("groq_model", "llama-4-scout-17b-16e-instruct")
    assert ok


def test_setup_input_groq_model_empty_rejected():
    ok, _ = validate_setup_input("groq_model", "")
    assert not ok


def test_sanitize_string_strips():
    assert sanitize_string("  hello  ") == "hello"


def test_sanitize_string_removes_nulls():
    assert "\x00" not in sanitize_string("a\x00b")


def test_sanitize_string_truncates():
    assert len(sanitize_string("x" * 1000, max_length=10)) == 10


def test_sanitize_path_expands_tilde():
    result = sanitize_path("~/foo")
    expected = str(Path("~/foo").expanduser().resolve())
    assert result == expected


def test_sanitize_string_non_string():
    assert sanitize_string(123) == "123"


def test_validate_tone_non_string():
    ok, _ = validate_tone(42)
    assert not ok


def test_validate_boolean():
    ok, _ = validate_boolean(True, "test")
    assert ok
    ok, _ = validate_boolean("yes", "test")
    assert not ok


def test_validate_rate_limit_invalid_types():
    cfg = {"enabled": "notbool", "cooldown_minutes": "invalid", "max_calls_per_day": "bad"}
    ok, msg = validate_rate_limit_config(cfg)
    assert not ok


def test_validate_rate_limit_out_of_range():
    cfg = {"enabled": True, "cooldown_minutes": 9999, "max_calls_per_day": 999}
    ok, _ = validate_rate_limit_config(cfg)
    assert not ok


def test_validate_quality_config_non_dict():
    ok, _ = validate_quality_config("not a dict")
    assert not ok


def test_validate_template_string_not_string():
    ok, _ = validate_template_string(42)
    assert not ok


def test_validate_template_string_nested_braces():
    ok, _ = validate_template_string("{{yesterday}}")
    assert not ok


def test_validate_template_string_no_variables():
    ok, _ = validate_template_string("No variables here")
    assert not ok


def test_validate_custom_templates_config_invalid_key():
    ok, _ = validate_custom_templates_config({"bad name!": "Done: {yesterday}"})
    assert not ok


def test_validate_provider_config_groq_invalid_api_key():
    cfg = {
        "name": "groq",
        "ollama": {"base_url": "http://localhost:11434", "model": "llama3"},
        "groq": {"api_key": "invalid_key", "model": "llama-3.1-8b-instant"},
    }
    ok, _ = validate_provider_config(cfg)
    assert not ok


def test_validate_positive_int_arg():
    assert validate_positive_int_arg("--test", "5") == 5
    with pytest.raises(argparse.ArgumentTypeError):
        validate_positive_int_arg("--test", "abc")
    with pytest.raises(argparse.ArgumentTypeError):
        validate_positive_int_arg("--test", "0")
    with pytest.raises(argparse.ArgumentTypeError):
        validate_positive_int_arg("--test", "300")


def test_parse_bool_text():
    assert parse_bool_text("yes") is True
    assert parse_bool_text("no") is False
    assert parse_bool_text("true") is True
    assert parse_bool_text("false") is False


def test_setup_input_cooldown_minutes():
    ok, _ = validate_setup_input("cooldown_minutes", "30")
    assert ok


def test_setup_input_cooldown_minutes_invalid():
    ok, _ = validate_setup_input("cooldown_minutes", "-1")
    assert not ok


def test_setup_input_max_calls():
    ok, _ = validate_setup_input("max_calls_per_day", "10")
    assert ok


def test_setup_input_max_calls_invalid():
    ok, _ = validate_setup_input("max_calls_per_day", "100")
    assert not ok


def test_setup_input_ollama_model_empty():
    ok, _ = validate_setup_input("ollama_model", "")
    assert not ok


def test_setup_input_ollama_base_url():
    ok, _ = validate_setup_input("ollama_base_url", "http://localhost:11434")
    assert ok


def test_setup_input_ollama_base_url_invalid():
    ok, _ = validate_setup_input("ollama_base_url", "not a url")
    assert not ok


def test_setup_input_groq_api_key():
    ok, _ = validate_setup_input("groq_api_key", "gsk_" + "a" * 40)
    assert ok


def test_setup_input_groq_api_key_empty():
    ok, _ = validate_setup_input("groq_api_key", "")
    assert ok


def test_setup_input_groq_api_key_invalid():
    ok, _ = validate_setup_input("groq_api_key", "short")
    assert not ok


def test_setup_input_boolean_text_true():
    ok, _ = validate_setup_input("quality_enabled", "yes")
    assert ok


def test_setup_input_boolean_text_invalid():
    ok, _ = validate_setup_input("quality_enabled", "maybe")
    assert not ok


def test_setup_input_quality_min_score():
    ok, _ = validate_setup_input("quality_min_score", "75")
    assert ok


def test_setup_input_quality_min_score_invalid():
    ok, _ = validate_setup_input("quality_min_score", "150")
    assert not ok


def test_setup_input_template_selection():
    ok, _ = validate_setup_input("template", "default")
    assert ok


def test_setup_input_template_selection_invalid():
    ok, _ = validate_setup_input("template", "nonexistent")
    assert not ok


def test_validate_cli_args_template_invalid():
    ns = argparse.Namespace(template="nonexistent")
    errors = validate_cli_args(ns, {})
    assert errors


def test_validate_cli_args_history_clear_with_limit():
    ns = argparse.Namespace(command="history", clear=True, limit=50)
    errors = validate_cli_args(ns, {})
    assert any("limit" in e for e in errors)


def test_validate_cli_args_warmup_install_uninstall():
    ns = argparse.Namespace(command="warm-up", install_startup=True, uninstall_startup=True)
    errors = validate_cli_args(ns, {})
    assert errors


def test_validate_full_config_repos_not_list():
    ok, errors = validate_full_config({"repos": "not a list"})
    assert not ok
    assert any("array" in e for e in errors)


def test_validate_full_config_repos_non_string_entry(tmp_path):
    config = _make_valid_config(tmp_path)
    config["repos"] = [123]
    ok, errors = validate_full_config(config)
    assert not ok
    assert any("non-empty string" in e for e in errors)


def test_validate_full_config_quality_and_template(tmp_path):
    config = _make_valid_config(tmp_path)
    config["quality"] = {"enabled": "bad", "min_score": -1, "show_breakdown": "nope"}
    config["template"] = "invalid_template"
    ok, errors = validate_full_config(config)
    assert not ok


def test_validate_full_config_noise_and_warmup(tmp_path):
    config = _make_valid_config(tmp_path)
    config["noise_filter_enabled"] = "not-bool"
    config["auto_warm_up"] = "also-not-bool"
    ok, errors = validate_full_config(config)
    assert not ok


def test_validate_resource_limits_hours_out_of_range(tmp_path):
    config = _make_valid_config(tmp_path)
    config["hours_lookback"] = 9999
    ok, errors = validate_resource_limits(config)
    assert not ok


def test_validate_template_string_format_specifier():
    ok, _ = validate_template_string("Hello {yesterday!s}")
    assert not ok


def test_validate_template_string_invalid_variable():
    ok, _ = validate_template_string("{unknown_var}")
    assert not ok


def test_validate_template_name_with_custom_templates():
    ok, _ = validate_template_name("my_template", {"my_template": "Done: {yesterday}"})
    assert ok


def test_validate_template_name_non_string():
    ok, _ = validate_template_name(123)
    assert not ok


def test_validate_setup_input_all_boolean_fields():
    for field in (
        "quality_enabled",
        "quality_show_breakdown",
        "noise_filter_enabled",
        "auto_warm_up",
    ):
        ok, _ = validate_setup_input(field, "true")
        assert ok, f"{field} should accept 'true'"
        ok, _ = validate_setup_input(field, "false")
        assert ok, f"{field} should accept 'false'"


def test_validate_provider_config_ollama_missing_model():
    cfg = {
        "name": "ollama",
        "ollama": {"base_url": "http://localhost:11434", "model": ""},
        "groq": {"api_key": "", "model": "llama-3.1-8b-instant"},
    }
    ok, _ = validate_provider_config(cfg)
    assert not ok


def test_validate_provider_config_not_dict():
    ok, _ = validate_provider_config("not a dict")
    assert not ok


def test_validate_custom_templates_config_exceeds_max():
    templates = {f"t{i:02d}": "Done: {yesterday}" for i in range(11)}
    ok, _ = validate_custom_templates_config(templates)
    assert not ok


def test_validate_custom_templates_invalid_template_content():
    templates = {"my_temp": "No variables"}
    ok, _ = validate_custom_templates_config(templates)
    assert not ok


def test_validate_full_config_rate_limit_and_provider(tmp_path):
    config = _make_valid_config(tmp_path)
    config["rate_limit"] = "not a dict"
    config["provider"] = "not a dict"
    ok, errors = validate_full_config(config)
    assert not ok


def test_validate_full_config_slack_webhook_invalid(tmp_path):
    config = _make_valid_config(tmp_path)
    config["slack_webhook_url"] = "https://example.com"
    ok, errors = validate_full_config(config)
    assert not ok


def test_path_is_within(tmp_path):
    from standup.validator import _path_is_within

    parent = tmp_path / "parent"
    child = parent / "child"
    parent.mkdir()
    child.mkdir()
    assert _path_is_within(child, parent) is True
    assert _path_is_within(parent, child) is False
    assert _path_is_within(tmp_path, parent) is False


def test_sanitize_path_non_string():
    result = sanitize_path(123)
    assert isinstance(result, str)


def test_sanitize_path_unc():
    result = sanitize_path("\\\\server\\share")
    assert result.startswith("\\\\") or result.startswith("//")


def test_validate_path_safety_non_string():
    ok, _ = validate_path_safety(123)
    assert not ok


def test_validate_repo_path_with_unsafe_path():
    ok, _ = validate_repo_path("//network/share")
    assert not ok


def test_validate_provider_config_ollama_not_dict():
    cfg = {"name": "ollama", "ollama": "not a dict", "groq": {"api_key": "", "model": "m"}}
    ok, _ = validate_provider_config(cfg)
    assert not ok


def test_validate_provider_config_ollama_invalid_url():
    cfg = {
        "name": "ollama",
        "ollama": {"base_url": "not a url", "model": "m"},
        "groq": {"api_key": "", "model": "m"},
    }
    ok, _ = validate_provider_config(cfg)
    assert not ok


def test_validate_provider_config_groq_not_dict():
    cfg = {
        "name": "groq",
        "ollama": {"base_url": "http://localhost:11434", "model": "m"},
        "groq": "not a dict",
    }
    ok, _ = validate_provider_config(cfg)
    assert not ok


def test_validate_quality_config_min_score_non_int():
    ok, _ = validate_quality_config(
        {"enabled": True, "min_score": "not an int", "show_breakdown": False}
    )
    assert not ok


def test_validate_custom_templates_config_not_dict():
    ok, _ = validate_custom_templates_config("not a dict")
    assert not ok


def test_validate_full_config_repos_path_safety(tmp_path):
    config = _make_valid_config(tmp_path)
    config["repos"] = ["//network/share"]
    ok, errors = validate_full_config(config)
    assert not ok


def test_validate_full_config_custom_templates_fail(tmp_path):
    config = _make_valid_config(tmp_path)
    config["custom_templates"] = {"bad name!": "Done: {yesterday}"}
    ok, errors = validate_full_config(config)
    assert not ok


def test_setup_input_cooldown_minutes_non_int():
    ok, _ = validate_setup_input("cooldown_minutes", "not a number")
    assert not ok


def test_setup_input_max_calls_non_int():
    ok, _ = validate_setup_input("max_calls_per_day", "not a number")
    assert not ok


def test_setup_input_quality_min_score_non_int():
    ok, _ = validate_setup_input("quality_min_score", "not a number")
    assert not ok


def test_setup_input_ollama_model_valid():
    ok, _ = validate_setup_input("ollama_model", "llama3")
    assert ok


def test_sanitize_path_resolve_fallback(monkeypatch):
    from pathlib import Path

    def _raise(*a, **kw):
        raise OSError("no resolve")

    monkeypatch.setattr(Path, "resolve", _raise)
    result = sanitize_path("~/foo")
    assert "foo" in result


def test_sanitize_path_absolute_fallback(monkeypatch):
    from pathlib import Path

    def _raise_resolve(*a, **kw):
        raise OSError("no resolve")

    monkeypatch.setattr(Path, "resolve", _raise_resolve)

    def _raise_absolute(*a, **kw):
        raise OSError("no absolute")

    monkeypatch.setattr(Path, "absolute", _raise_absolute)
    result = sanitize_path("~/foo")
    assert "foo" in result


def test_validate_path_safety_candidate_exception(monkeypatch):
    from pathlib import Path

    def _raise(*a, **kw):
        raise OSError("no absolute")

    monkeypatch.setattr(Path, "absolute", _raise)
    ok, _ = validate_path_safety(str(Path.home() / "test"))
    assert not ok


def test_validate_path_safety_resolve_exception(monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(Path, "exists", lambda self: True)

    def _raise(*a, **kw):
        raise OSError("no resolve")

    monkeypatch.setattr(Path, "resolve", _raise)
    ok, _ = validate_path_safety(str(Path.home() / "test"))
    assert not ok


def test_validate_path_safety_traversal(tmp_path, monkeypatch):
    from pathlib import Path

    test_path = tmp_path / "tricky"
    monkeypatch.setattr(Path, "exists", lambda self: "tricky" not in str(self))
    original_resolve = Path.resolve

    def _fake_resolve(self):
        if "tricky" in str(self):
            return Path(str(self).replace("tricky", "safe"))
        return original_resolve(self)

    monkeypatch.setattr(Path, "resolve", _fake_resolve)
    ok, _ = validate_path_safety(str(test_path))
    assert not ok
