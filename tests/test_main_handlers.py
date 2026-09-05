"""Tests for main.py subcommand handlers and dispatch."""

import argparse
from unittest.mock import MagicMock

import pytest

import standup.main as main_mod


def _dispatch_config() -> dict:
    return {"provider": {"name": "ollama"}, "custom_templates": {}}


def test_handle_version(capsys):
    main_mod._handle_version()
    assert "StandupBot v" in capsys.readouterr().out


def test_handle_changelog_exists(capsys):
    main_mod._handle_changelog()
    assert capsys.readouterr().out.strip() != ""


def test_handle_changelog_missing(monkeypatch, capsys):
    monkeypatch.setattr("pathlib.Path.exists", lambda self: False)
    main_mod._handle_changelog()
    assert "CHANGELOG.md not found" in capsys.readouterr().out


def test_handle_doctor(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr("standup.security.run_doctor", mock)
    main_mod._handle_doctor()
    mock.assert_called_once()


def test_handle_usage(monkeypatch, capsys):
    monkeypatch.setattr("standup.rate_limiter.get_usage_report", lambda: "usage-report")
    main_mod._handle_usage()
    assert "usage-report" in capsys.readouterr().out


def test_handle_logs_clear_cancelled(monkeypatch, capsys):
    monkeypatch.setattr(main_mod, "_confirm_action", lambda prompt: False)
    main_mod._handle_logs(argparse.Namespace(clear=True, tail=20))
    assert "cancelled" in capsys.readouterr().out


def test_handle_logs_cleared(monkeypatch, capsys):
    monkeypatch.setattr(main_mod, "_confirm_action", lambda prompt: True)
    monkeypatch.setattr(main_mod, "clear_logs", lambda: True)
    main_mod._handle_logs(argparse.Namespace(clear=True, tail=20))
    assert "cleared" in capsys.readouterr().out


def test_handle_logs_clear_failed(monkeypatch, capsys):
    monkeypatch.setattr(main_mod, "_confirm_action", lambda prompt: True)
    monkeypatch.setattr(main_mod, "clear_logs", lambda: False)
    main_mod._handle_logs(argparse.Namespace(clear=True, tail=20))
    assert "Could not clear" in capsys.readouterr().out


def test_handle_logs_empty(monkeypatch, capsys):
    monkeypatch.setattr(main_mod, "read_log_entries", lambda tail: [])
    main_mod._handle_logs(argparse.Namespace(clear=False, tail=20))
    assert "No structured logs" in capsys.readouterr().out


def test_handle_logs_entries(monkeypatch, capsys):
    entries = [
        {"ts": "2026-09-04T10:00:00", "event": "app_start", "level": "INFO", "a": 1},
        {"ts": "2026-09-04T10:01:00", "event": "x", "level": "INFO"},
    ]
    monkeypatch.setattr(main_mod, "read_log_entries", lambda tail: entries)
    main_mod._handle_logs(argparse.Namespace(clear=False, tail=20))
    assert "Standup Logs" in capsys.readouterr().out


class _StubOllama:
    def __init__(self, config):
        pass

    def list_local_models(self):
        return ["llama3"]


class _StubOllamaEmpty:
    def __init__(self, config):
        pass

    def list_local_models(self):
        return []


def test_handle_models_found(monkeypatch, capsys):
    monkeypatch.setattr("standup.llm.ollama_provider.OllamaProvider", _StubOllama)
    main_mod._handle_models({})
    assert "llama3" in capsys.readouterr().out


def test_handle_models_none(monkeypatch, capsys):
    monkeypatch.setattr("standup.llm.ollama_provider.OllamaProvider", _StubOllamaEmpty)
    main_mod._handle_models({})
    assert "No models found" in capsys.readouterr().out


def test_handle_templates_cmd(monkeypatch, capsys):
    monkeypatch.setattr("standup.templates.list_templates", lambda custom: ["default", "mine"])
    main_mod._handle_templates_cmd({"custom_templates": {"mine": "x"}})
    out = capsys.readouterr().out
    assert "Standup Templates" in out


def test_handle_history_clear_cancelled(monkeypatch, capsys):
    monkeypatch.setattr(main_mod, "_confirm_action", lambda prompt: False)
    main_mod._handle_history(argparse.Namespace(clear=True, days=None, limit=10))
    assert "cancelled" in capsys.readouterr().out


def test_handle_history_cleared(monkeypatch, capsys):
    monkeypatch.setattr(main_mod, "_confirm_action", lambda prompt: True)
    monkeypatch.setattr("standup.history.clear_history", lambda days: 2)
    main_mod._handle_history(argparse.Namespace(clear=True, days=None, limit=10))
    assert "Deleted 2 history entries" in capsys.readouterr().out


def test_handle_history_empty(monkeypatch, capsys):
    monkeypatch.setattr("standup.history.get_history", lambda limit: [])
    main_mod._handle_history(argparse.Namespace(clear=False, days=None, limit=10))
    assert "No standup history" in capsys.readouterr().out


def test_handle_history_entries(monkeypatch, capsys):
    entries = [
        {
            "created_at": "2026-09-04T10:00:00",
            "standup_text": "did things",
            "repos": ["app"],
            "provider": "groq",
        }
    ]
    monkeypatch.setattr("standup.history.get_history", lambda limit: entries)
    main_mod._handle_history(argparse.Namespace(clear=False, days=None, limit=10))
    assert "Standup History" in capsys.readouterr().out


def test_handle_warmup_install(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(main_mod, "_install_startup", mock)
    main_mod._handle_warmup(
        argparse.Namespace(install_startup=True, uninstall_startup=False, provider=None),
        {},
    )
    mock.assert_called_once()


def test_handle_warmup_uninstall(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(main_mod, "_uninstall_startup", mock)
    main_mod._handle_warmup(
        argparse.Namespace(install_startup=False, uninstall_startup=True, provider=None),
        {},
    )
    mock.assert_called_once()


def test_handle_warmup_success(monkeypatch):
    monkeypatch.setattr(
        "standup.llm.factory.get_provider_with_fallback",
        lambda cfg, override=None: object(),
    )
    monkeypatch.setattr("standup.warmup.warm_up_provider", lambda provider, verbose=True: True)
    main_mod._handle_warmup(
        argparse.Namespace(install_startup=False, uninstall_startup=False, provider=None),
        {},
    )


def test_handle_warmup_failure(monkeypatch):
    monkeypatch.setattr(
        "standup.llm.factory.get_provider_with_fallback",
        lambda cfg, override=None: object(),
    )
    monkeypatch.setattr("standup.warmup.warm_up_provider", lambda provider, verbose=True: False)
    with pytest.raises(SystemExit):
        main_mod._handle_warmup(
            argparse.Namespace(install_startup=False, uninstall_startup=False, provider=None),
            {},
        )


def test_handle_maintenance(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(main_mod, "_run_maintenance", mock)
    main_mod._handle_maintenance()
    mock.assert_called_once()


def test_install_startup_writes_and_registers(tmp_path, monkeypatch):
    script = tmp_path / "s.ps1"
    definition = tmp_path / "d.xml"
    monkeypatch.setattr(
        main_mod,
        "_startup_paths",
        lambda: {"base_dir": tmp_path, "script": script, "definition": definition},
    )
    monkeypatch.setattr(main_mod, "_confirm_action", lambda prompt: True)
    monkeypatch.setattr(
        "standup.warmup.get_warm_up_script_content", lambda cfg: "standup warm-up\n"
    )
    monkeypatch.setattr("standup.security.enforce_file_permissions", lambda *a, **kw: None)
    monkeypatch.setattr("standup.main.sys.platform", "linux")
    run_mock = MagicMock()
    monkeypatch.setattr(main_mod.subprocess, "run", run_mock)
    main_mod._install_startup({"provider": {}})
    assert script.exists()
    assert definition.exists()
    assert run_mock.call_count == 2


def test_install_startup_cancelled(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        main_mod,
        "_startup_paths",
        lambda: {
            "base_dir": tmp_path,
            "script": tmp_path / "s.ps1",
            "definition": tmp_path / "d.xml",
        },
    )
    monkeypatch.setattr(main_mod, "_confirm_action", lambda prompt: False)
    monkeypatch.setattr(
        "standup.warmup.get_warm_up_script_content", lambda cfg: "standup warm-up\n"
    )
    main_mod._install_startup({"provider": {}})
    assert "cancelled" in capsys.readouterr().out


def test_uninstall_startup_removes_files(tmp_path, monkeypatch):
    script = tmp_path / "s.ps1"
    definition = tmp_path / "d.xml"
    script.write_text("x")
    definition.write_text("y")
    monkeypatch.setattr(
        main_mod,
        "_startup_paths",
        lambda: {"base_dir": tmp_path, "script": script, "definition": definition},
    )
    monkeypatch.setattr(main_mod, "_confirm_action", lambda prompt: True)
    monkeypatch.setattr("standup.main.sys.platform", "linux")
    run_mock = MagicMock()
    monkeypatch.setattr(main_mod.subprocess, "run", run_mock)
    main_mod._uninstall_startup()
    assert not script.exists()
    assert not definition.exists()


def test_uninstall_startup_cancelled(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(main_mod, "_startup_paths", lambda: {"base_dir": tmp_path})
    monkeypatch.setattr(main_mod, "_confirm_action", lambda prompt: False)
    main_mod._uninstall_startup()
    assert "cancelled" in capsys.readouterr().out


def _patch_dispatch(monkeypatch, tmp_path, argv):
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr("standup.config.load_config", lambda: _dispatch_config())
    monkeypatch.setattr("standup.logger.get_log_path", lambda: str(tmp_path / "s.log"))


def test_main_dispatches_version(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["standup", "--version"])
    main_mod.main()
    assert "StandupBot v" in capsys.readouterr().out


def test_main_dispatches_changelog(monkeypatch, tmp_path):
    _patch_dispatch(monkeypatch, tmp_path, ["standup"])
    mock = MagicMock()
    monkeypatch.setattr(main_mod, "_handle_changelog", mock)
    monkeypatch.setattr("sys.argv", ["standup", "--changelog"])
    main_mod.main()
    mock.assert_called_once()


def test_main_dispatches_setup(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(main_mod, "run_setup_wizard", mock)
    monkeypatch.setattr("sys.argv", ["standup", "--setup"])
    main_mod.main()
    mock.assert_called_once()


def test_main_dispatches_doctor(monkeypatch, tmp_path):
    _patch_dispatch(monkeypatch, tmp_path, ["standup", "doctor"])
    mock = MagicMock()
    monkeypatch.setattr(main_mod, "_handle_doctor", mock)
    main_mod.main()
    mock.assert_called_once()


def test_main_dispatches_usage(monkeypatch, tmp_path):
    _patch_dispatch(monkeypatch, tmp_path, ["standup", "usage"])
    mock = MagicMock()
    monkeypatch.setattr(main_mod, "_handle_usage", mock)
    main_mod.main()
    mock.assert_called_once()


def test_main_dispatches_logs(monkeypatch, tmp_path):
    _patch_dispatch(monkeypatch, tmp_path, ["standup", "logs"])
    mock = MagicMock()
    monkeypatch.setattr(main_mod, "_handle_logs", mock)
    main_mod.main()
    mock.assert_called_once()


def test_main_dispatches_models(monkeypatch, tmp_path):
    _patch_dispatch(monkeypatch, tmp_path, ["standup", "models"])
    mock = MagicMock()
    monkeypatch.setattr(main_mod, "_handle_models", mock)
    main_mod.main()
    mock.assert_called_once()


def test_main_dispatches_templates(monkeypatch, tmp_path):
    _patch_dispatch(monkeypatch, tmp_path, ["standup", "templates"])
    mock = MagicMock()
    monkeypatch.setattr(main_mod, "_handle_templates_cmd", mock)
    main_mod.main()
    mock.assert_called_once()


def test_main_dispatches_history(monkeypatch, tmp_path):
    _patch_dispatch(monkeypatch, tmp_path, ["standup", "history"])
    mock = MagicMock()
    monkeypatch.setattr(main_mod, "_handle_history", mock)
    main_mod.main()
    mock.assert_called_once()


def test_main_dispatches_warmup(monkeypatch, tmp_path):
    _patch_dispatch(monkeypatch, tmp_path, ["standup", "warm-up"])
    mock = MagicMock()
    monkeypatch.setattr(main_mod, "_handle_warmup", mock)
    main_mod.main()
    mock.assert_called_once()


def test_main_dispatches_maintenance(monkeypatch, tmp_path):
    _patch_dispatch(monkeypatch, tmp_path, ["standup", "--maintenance"])
    mock = MagicMock()
    monkeypatch.setattr(main_mod, "_handle_maintenance", mock)
    main_mod.main()
    mock.assert_called_once()
