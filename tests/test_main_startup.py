"""Tests for the login-time startup integration helpers in standup/main.py."""

import standup.main as main_mod


def test_linux_startup_paths_include_a_script_file(monkeypatch):
    monkeypatch.setattr("standup.main.sys.platform", "linux")
    paths = main_mod._startup_paths()
    assert "script" in paths
    assert paths["script"].name == "standupbot-warmup.sh"
    assert paths["definition"].name == "standupbot-warmup.service"


def test_linux_service_execstart_is_a_single_line_referencing_script_path(monkeypatch):
    monkeypatch.setattr("standup.main.sys.platform", "linux")
    script_content = "#!/usr/bin/env bash\n# comment\nstandup warm-up\n"
    paths = main_mod._startup_paths()
    result = main_mod._startup_definition_content(paths, script_content)

    assert result["script"] == script_content
    exec_lines = [
        line for line in result["definition"].splitlines() if line.startswith("ExecStart=")
    ]
    assert len(exec_lines) == 1
    assert exec_lines[0] == f"ExecStart=/bin/bash {paths['script']}"
    # The fixed ExecStart line must not contain a raw newline (which would
    # break systemd's ini-style unit file parser).
    assert "\n" not in exec_lines[0]


def test_windows_xml_declares_utf8_matching_how_it_is_written(monkeypatch):
    monkeypatch.setattr("standup.main.sys.platform", "win32")
    script_content = "standup warm-up\n"
    paths = main_mod._startup_paths()
    result = main_mod._startup_definition_content(paths, script_content)

    assert result["definition"].startswith('<?xml version="1.0" encoding="UTF-8"?>')


def test_macos_plist_is_well_formed_xml(monkeypatch):
    import xml.dom.minidom as minidom

    monkeypatch.setattr("standup.main.sys.platform", "darwin")
    script_content = "#!/usr/bin/env bash\n# comment\nstandup warm-up\n"
    paths = main_mod._startup_paths()
    result = main_mod._startup_definition_content(paths, script_content)

    minidom.parseString(result["definition"])  # raises on malformed XML


# ---------------------------------------------------------------------------
# Regression tests: rate-limit/cache ordering bug.
# ---------------------------------------------------------------------------


class _DummyProvider:
    model = "dummy-model"

    def is_available(self) -> bool:
        return True

    def get_provider_name(self) -> str:
        return "Dummy"

    def generate_standup(self, prompt: str, tone: str) -> str:
        return "**Yesterday:** stuff\n**Today:** more stuff\n**Blockers:** None"


def _make_test_repo(tmp_path):
    import git as git_module

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    repo = git_module.Repo.init(str(repo_dir))
    with repo.config_writer() as cw:
        cw.set_value("user", "email", "a@b.com")
        cw.set_value("user", "name", "Test")
    (repo_dir / "f.txt").write_text("hi")
    repo.index.add(["f.txt"])
    repo.index.commit("feat: add file")
    return str(repo_dir)


def _base_config(repo_path: str) -> dict:
    return {
        "repos": [repo_path],
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
        "quality": {"enabled": False, "min_score": 0, "show_breakdown": False},
        "noise_filter_enabled": False,
        "template": "default",
        "custom_templates": {},
        "auto_warm_up": False,
    }


def _patch_common(monkeypatch, tmp_path, config, cached_entry):
    monkeypatch.setattr("sys.argv", ["standup"])
    monkeypatch.setattr("standup.config.load_config", lambda: config)
    monkeypatch.setattr(
        "standup.llm.factory.get_provider_with_fallback",
        lambda cfg, override=None: _DummyProvider(),
    )
    monkeypatch.setattr(
        "standup.history.find_cached_standup_entry",
        lambda *a, **kw: cached_entry,
    )
    monkeypatch.setattr("standup.history.save_standup", lambda *a, **kw: None)
    monkeypatch.setattr("standup.rate_limiter.USAGE_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setattr("standup.logger.get_log_path", lambda: str(tmp_path / "standup.log"))


def test_cache_hit_never_calls_enforce_rate_limit(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    repo_path = _make_test_repo(tmp_path)
    config = _base_config(repo_path)
    cached_entry = {
        "standup_text": "**Yesterday:** cached\n**Today:** cached\n**Blockers:** None",
        "quality_score": 80,
        "created_at": "2026-06-20T09:00:00",
    }
    _patch_common(monkeypatch, tmp_path, config, cached_entry)

    rate_limit_mock = MagicMock()
    monkeypatch.setattr("standup.rate_limiter.enforce_rate_limit", rate_limit_mock)

    main_mod.main()

    rate_limit_mock.assert_not_called()


def test_cache_miss_still_calls_enforce_rate_limit(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    repo_path = _make_test_repo(tmp_path)
    config = _base_config(repo_path)
    _patch_common(monkeypatch, tmp_path, config, cached_entry=None)

    rate_limit_mock = MagicMock()
    monkeypatch.setattr("standup.rate_limiter.enforce_rate_limit", rate_limit_mock)
    monkeypatch.setattr("standup.rate_limiter.load_usage", lambda: {})
    monkeypatch.setattr("standup.rate_limiter.record_call", lambda usage: usage)
    monkeypatch.setattr("standup.rate_limiter.save_usage", lambda usage: None)

    main_mod.main()

    rate_limit_mock.assert_called_once()
