"""Tests for isolated helper functions in standup/main.py."""

import sys
import types
from pathlib import Path

from datetime import datetime

from standup.main import (
    _confirm_action,
    _get_provider_model,
    _get_provider_slug,
    _get_repo_names,
    _startup_paths,
)


def test_get_provider_slug_ollama():
    from standup.llm.ollama_provider import OllamaProvider
    provider = object.__new__(OllamaProvider)
    assert _get_provider_slug(provider) == "ollama"


def test_get_provider_slug_groq():
    from standup.llm.groq_provider import GroqProvider
    provider = object.__new__(GroqProvider)
    assert _get_provider_slug(provider) == "groq"


def test_get_provider_slug_unknown():
    class CustomProvider:
        pass
    assert _get_provider_slug(CustomProvider()) == "customprovider"


def test_get_provider_model_has_attr():
    provider = types.SimpleNamespace(model="llama3")
    assert _get_provider_model(provider) == "llama3"


def test_get_provider_model_missing_attr():
    provider = object()
    assert _get_provider_model(provider) == "unknown"


def test_get_repo_names_empty():
    assert _get_repo_names([]) == []


def test_get_repo_names_single():
    commits = [{"repo": "app"}]
    assert _get_repo_names(commits) == ["app"]


def test_get_repo_names_deduplicates():
    commits = [{"repo": "app"}, {"repo": "api"}, {"repo": "app"}]
    assert _get_repo_names(commits) == ["api", "app"]


def test_get_repo_names_skips_empty():
    commits = [{"repo": "app"}, {"repo": ""}, {"repo": "api"}]
    assert _get_repo_names(commits) == ["api", "app"]


def test_get_repo_names_no_repo_key():
    commits = [{"message": "fix"}]
    assert _get_repo_names(commits) == []


def test_confirm_action_yes(monkeypatch):
    monkeypatch.setattr("standup.main._prompt", lambda label, default: "yes")
    assert _confirm_action("Proceed?") is True


def test_confirm_action_no(monkeypatch):
    monkeypatch.setattr("standup.main._prompt", lambda label, default: "no")
    assert _confirm_action("Proceed?") is False


def test_confirm_action_y(monkeypatch):
    monkeypatch.setattr("standup.main._prompt", lambda label, default: "y")
    assert _confirm_action("Proceed?") is True


def test_startup_paths_windows(monkeypatch):
    monkeypatch.setattr("standup.main.sys.platform", "win32")
    paths = _startup_paths()
    assert "script" in paths
    assert paths["script"].name == "standupbot-warmup.ps1"
    assert paths["definition"].name == "standupbot-warmup.xml"


def test_startup_paths_darwin(monkeypatch):
    monkeypatch.setattr("standup.main.sys.platform", "darwin")
    paths = _startup_paths()
    assert "script" not in paths
    assert "definition" in paths
    assert paths["definition"].name == "com.standupbot.warmup.plist"


def test_startup_paths_linux(monkeypatch):
    monkeypatch.setattr("standup.main.sys.platform", "linux")
    paths = _startup_paths()
    assert "script" in paths
    assert "definition" in paths
    assert paths["script"].name == "standupbot-warmup.sh"
    assert paths["definition"].name == "standupbot-warmup.service"


def test_show_quality_breakdown_strengths(monkeypatch, capsys):
    from standup.main import _show_quality_breakdown
    quality = {"score": 80, "strengths": ["well documented", "good messages"], "issues": []}
    _show_quality_breakdown(quality)
    out = capsys.readouterr().out
    assert "well documented" in out
    assert "issues" not in out.lower()


def test_show_quality_breakdown_issues(monkeypatch, capsys):
    from standup.main import _show_quality_breakdown
    quality = {"issues": ["too long", "missing scope"], "strengths": []}
    _show_quality_breakdown(quality)
    out = capsys.readouterr().out
    assert "too long" in out
    assert "strengths" not in out.lower()


def test_show_quality_breakdown_no_data(capsys):
    from standup.main import _show_quality_breakdown
    quality = {"strengths": None, "issues": None}
    _show_quality_breakdown(quality)
    out = capsys.readouterr().out
    assert out == ""


def test_should_auto_warm_up_disabled(monkeypatch):
    from standup.main import _should_auto_warm_up
    assert _should_auto_warm_up(object(), {"auto_warm_up": False}) is False


def test_should_auto_warm_up_import_error(monkeypatch):
    import builtins
    original_import = builtins.__import__
    def _fake_import(name, *args, **kwargs):
        if name == "standup.warmup":
            raise ImportError("simulated")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", _fake_import)
    from standup.main import _should_auto_warm_up
    provider = object.__new__(type("Fake", (), {}))
    assert _should_auto_warm_up(provider, {"auto_warm_up": True}) is False


def test_should_auto_warm_up_non_ollama():
    from standup.main import _should_auto_warm_up
    from standup.llm.groq_provider import GroqProvider
    provider = object.__new__(GroqProvider)
    assert _should_auto_warm_up(provider, {"auto_warm_up": True}) is False


def test_should_auto_warm_up_already_warm(monkeypatch):
    monkeypatch.setattr("standup.warmup.is_model_warm", lambda p: True)
    from standup.main import _should_auto_warm_up
    from standup.llm.ollama_provider import OllamaProvider
    provider = object.__new__(OllamaProvider)
    assert _should_auto_warm_up(provider, {"auto_warm_up": True}) is False


def test_post_to_slack_success(monkeypatch, capsys):
    from standup.main import _post_to_slack
    class FakeResponse:
        status_code = 200
    monkeypatch.setattr("requests.post", lambda *a, **kw: FakeResponse())
    _post_to_slack("https://hooks.slack.com/x", "hello")
    out = capsys.readouterr().out
    assert "Posted to Slack" in out


def test_post_to_slack_http_error(monkeypatch, capsys):
    from standup.main import _post_to_slack
    class FakeResponse:
        status_code = 400
        text = "bad request"
    monkeypatch.setattr("requests.post", lambda *a, **kw: FakeResponse())
    _post_to_slack("https://hooks.slack.com/x", "hello")
    out = capsys.readouterr().out
    assert "Slack post failed" in out


def test_post_to_slack_exception(monkeypatch, capsys):
    from standup.main import _post_to_slack
    def _raise(*a, **kw):
        raise ConnectionError("network error")
    monkeypatch.setattr("requests.post", _raise)
    _post_to_slack("https://hooks.slack.com/x", "hello")
    out = capsys.readouterr().out
    assert "Slack post error" in out


def test_startup_definition_content_windows(monkeypatch):
    from standup.main import _startup_definition_content
    monkeypatch.setattr("standup.main.sys.platform", "win32")
    paths = _startup_paths()
    result = _startup_definition_content(paths, "echo hello")
    assert "script" in result
    assert "definition" in result
    assert "powershell.exe" in result["definition"]


def test_startup_definition_content_darwin(monkeypatch):
    from standup.main import _startup_definition_content
    monkeypatch.setattr("standup.main.sys.platform", "darwin")
    paths = _startup_paths()
    result = _startup_definition_content(paths, "echo hello")
    assert "script" not in result
    assert "definition" in result
    assert "/bin/bash" in result["definition"]


def test_startup_definition_content_linux(monkeypatch):
    from standup.main import _startup_definition_content
    monkeypatch.setattr("standup.main.sys.platform", "linux")
    paths = _startup_paths()
    result = _startup_definition_content(paths, "echo hello")
    assert "script" in result
    assert "definition" in result
    assert "systemd" in result["definition"]


def test_prompt_keyboard_interrupt(monkeypatch):
    from standup.main import _prompt
    def _raise(*a):
        raise KeyboardInterrupt()
    monkeypatch.setattr("standup.main.console.input", _raise)
    import pytest
    with pytest.raises(SystemExit):
        _prompt("test", "default")


def test_prompt_eof_error(monkeypatch):
    from standup.main import _prompt
    def _raise(*a):
        raise EOFError()
    monkeypatch.setattr("standup.main.console.input", _raise)
    import pytest
    with pytest.raises(SystemExit):
        _prompt("test", "")


def test_prompt_bool_valid_input(monkeypatch):
    from standup.main import _prompt_bool
    monkeypatch.setattr("standup.main._prompt", lambda label, default: "yes")
    assert _prompt_bool("noise_filter_enabled", True) is True


def test_prompt_bool_invalid_then_valid(monkeypatch, capsys):
    from standup.main import _prompt_bool
    inputs = iter(["invalid", "no"])
    monkeypatch.setattr("standup.main._prompt", lambda label, default: next(inputs))
    assert _prompt_bool("noise_filter_enabled", True) is False
    out = capsys.readouterr().out
    assert "Enter yes/no or true/false" in out


def test_should_auto_warm_up_needs_warmup(monkeypatch):
    monkeypatch.setattr("standup.warmup.is_model_warm", lambda p: False)
    monkeypatch.setattr("standup.history.get_history", lambda **kw: [])
    from standup.main import _should_auto_warm_up
    from standup.llm.ollama_provider import OllamaProvider
    provider = object.__new__(OllamaProvider)
    assert _should_auto_warm_up(provider, {"auto_warm_up": True}) is True


def test_should_auto_warm_up_with_history_wrong_provider(monkeypatch):
    monkeypatch.setattr("standup.warmup.is_model_warm", lambda p: False)
    now = datetime.now()
    entries = [{"provider": "groq", "model": "mixtral", "created_at": now.isoformat()}]
    monkeypatch.setattr("standup.history.get_history", lambda **kw: entries)
    from standup.main import _should_auto_warm_up
    from standup.llm.ollama_provider import OllamaProvider
    provider = object.__new__(OllamaProvider)
    monkeypatch.setattr("standup.main._get_provider_model", lambda p: "llama3")
    assert _should_auto_warm_up(provider, {"auto_warm_up": True}) is True


def test_should_auto_warm_up_with_history_wrong_model(monkeypatch):
    monkeypatch.setattr("standup.warmup.is_model_warm", lambda p: False)
    now = datetime.now()
    entries = [{"provider": "ollama", "model": "mixtral", "created_at": now.isoformat()}]
    monkeypatch.setattr("standup.history.get_history", lambda **kw: entries)
    from standup.main import _should_auto_warm_up
    from standup.llm.ollama_provider import OllamaProvider
    provider = object.__new__(OllamaProvider)
    monkeypatch.setattr("standup.main._get_provider_model", lambda p: "llama3")
    assert _should_auto_warm_up(provider, {"auto_warm_up": True}) is True


def test_should_auto_warm_up_with_history_invalid_date(monkeypatch):
    monkeypatch.setattr("standup.warmup.is_model_warm", lambda p: False)
    entries = [{"provider": "ollama", "model": "llama3", "created_at": "not-a-date"}]
    monkeypatch.setattr("standup.history.get_history", lambda **kw: entries)
    from standup.main import _should_auto_warm_up
    from standup.llm.ollama_provider import OllamaProvider
    provider = object.__new__(OllamaProvider)
    monkeypatch.setattr("standup.main._get_provider_model", lambda p: "llama3")
    assert _should_auto_warm_up(provider, {"auto_warm_up": True}) is True


def test_should_auto_warm_up_with_history_recent_entry(monkeypatch):
    monkeypatch.setattr("standup.warmup.is_model_warm", lambda p: False)
    now = datetime.now()
    entries = [{"provider": "ollama", "model": "llama3", "created_at": now.isoformat()}]
    monkeypatch.setattr("standup.history.get_history", lambda **kw: entries)
    from standup.main import _should_auto_warm_up
    from standup.llm.ollama_provider import OllamaProvider
    provider = object.__new__(OllamaProvider)
    monkeypatch.setattr("standup.main._get_provider_model", lambda p: "llama3")
    assert _should_auto_warm_up(provider, {"auto_warm_up": True}) is False


def test_render_final_output(monkeypatch):
    from standup.main import _render_final_output
    monkeypatch.setattr("standup.templates.get_template", lambda name, custom: "Done: {yesterday}")
    monkeypatch.setattr("standup.templates.build_template_variables", lambda *a, **kw: {"yesterday": "fixed bugs"})
    monkeypatch.setattr("standup.templates.render_template", lambda tmpl, vars: "Done: fixed bugs")
    result = _render_final_output("bugs fixed", "default", {}, [{"repo": "app"}], "ollama")
    assert "Done" in result


def test_run_maintenance(monkeypatch, capsys):
    from standup.main import _run_maintenance
    monkeypatch.setattr("standup.history.auto_cleanup_if_needed", lambda: None)
    monkeypatch.setattr("standup.rate_limiter.load_usage", lambda: {})
    monkeypatch.setattr("standup.rate_limiter.save_usage", lambda u: None)
    monkeypatch.setattr("standup.logger.rotate_logs_if_needed", lambda: False)
    _run_maintenance()
    out = capsys.readouterr().out
    assert "Maintenance" in out
