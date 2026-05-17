"""Tests for standup/config.py."""

import json
from pathlib import Path

import pytest

from standup.config import _deep_merge, save_config


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------


def test_deep_merge_adds_missing_keys():
    base = {"a": 1, "b": {"c": 2}}
    override = {"b": {"d": 3}}
    result = _deep_merge(base, override)
    assert result["b"]["c"] == 2
    assert result["b"]["d"] == 3


def test_deep_merge_overrides_scalars():
    base = {"a": 1}
    override = {"a": 99}
    result = _deep_merge(base, override)
    assert result["a"] == 99


def test_deep_merge_does_not_mutate_base():
    base = {"a": {"b": 1}}
    override = {"a": {"b": 2}}
    _deep_merge(base, override)
    assert base["a"]["b"] == 1


def test_deep_merge_nested():
    base = {"provider": {"name": "ollama", "ollama": {"model": "llama3"}}}
    override = {"provider": {"name": "groq"}}
    result = _deep_merge(base, override)
    assert result["provider"]["name"] == "groq"
    assert result["provider"]["ollama"]["model"] == "llama3"


# ---------------------------------------------------------------------------
# save_config
# ---------------------------------------------------------------------------


def test_save_config_writes_json(tmp_path, monkeypatch):
    cfg_path = tmp_path / ".standup.json"
    monkeypatch.setattr("standup.config.CONFIG_PATH", str(cfg_path))

    config = {
        "repos": [],
        "author_email": "",
        "hours_lookback": 24,
        "tone": "casual",
        "slack_webhook_url": "",
        "provider": {
            "name": "ollama",
            "ollama": {"base_url": "http://localhost:11434", "model": "llama3"},
            "groq": {"api_key": "", "model": "llama3-8b-8192"},
        },
        "rate_limit": {"cooldown_minutes": 30, "max_calls_per_day": 10, "enabled": True},
    }
    save_config(config)
    data = json.loads(cfg_path.read_text())
    assert data["tone"] == "casual"
    assert data["provider"]["name"] == "ollama"


def test_save_config_valid_json(tmp_path, monkeypatch):
    cfg_path = tmp_path / ".standup.json"
    monkeypatch.setattr("standup.config.CONFIG_PATH", str(cfg_path))
    save_config({"tone": "formal", "repos": [], "author_email": "",
                 "hours_lookback": 24, "slack_webhook_url": "",
                 "provider": {"name": "ollama",
                              "ollama": {"base_url": "http://localhost:11434", "model": "llama3"},
                              "groq": {"api_key": "", "model": "llama3-8b-8192"}},
                 "rate_limit": {"cooldown_minutes": 30, "max_calls_per_day": 10, "enabled": True}})
    # Should parse without error
    data = json.loads(cfg_path.read_text())
    assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# load_config (integration-style)
# ---------------------------------------------------------------------------


def _valid_config_dict(tmp_path) -> dict:
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
            "groq": {"api_key": "", "model": "llama3-8b-8192"},
        },
        "rate_limit": {"cooldown_minutes": 30, "max_calls_per_day": 10, "enabled": True},
    }


def test_load_config_returns_dict(tmp_path, monkeypatch):
    from standup.config import load_config

    cfg_path = tmp_path / ".standup.json"
    config_data = _valid_config_dict(tmp_path)
    cfg_path.write_text(json.dumps(config_data))
    monkeypatch.setattr("standup.config.CONFIG_PATH", str(cfg_path))

    config = load_config()
    assert isinstance(config, dict)
    assert "repos" in config


def test_load_config_fills_defaults(tmp_path, monkeypatch):
    from standup.config import load_config

    cfg_path = tmp_path / ".standup.json"
    cfg_path.write_text(json.dumps({"tone": "formal"}))
    monkeypatch.setattr("standup.config.CONFIG_PATH", str(cfg_path))

    config = load_config()
    assert "hours_lookback" in config
    assert config["hours_lookback"] == 24


def test_load_config_invalid_json_exits(tmp_path, monkeypatch):
    from standup.config import load_config

    cfg_path = tmp_path / ".standup.json"
    cfg_path.write_text("{ invalid json }")
    monkeypatch.setattr("standup.config.CONFIG_PATH", str(cfg_path))

    with pytest.raises(SystemExit):
        load_config()


def test_load_config_resolves_groq_env_var(tmp_path, monkeypatch):
    from standup.config import load_config

    cfg_path = tmp_path / ".standup.json"
    cfg_path.write_text(json.dumps({}))
    monkeypatch.setattr("standup.config.CONFIG_PATH", str(cfg_path))
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "x" * 40)

    config = load_config()
    assert config["provider"]["groq"]["api_key"].startswith("gsk_")