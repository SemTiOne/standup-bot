"""Tests for standup/config.py."""

import json

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


def test_deep_merge_result_shares_no_references_with_base():
    base = {"provider": {"groq": {"api_key": ""}}}
    override = {"tone": "formal"}
    result = _deep_merge(base, override)

    assert result["provider"] is not base["provider"]
    assert result["provider"]["groq"] is not base["provider"]["groq"]

    result["provider"]["groq"]["api_key"] = "gsk_leaked"
    assert base["provider"]["groq"]["api_key"] == ""


def test_load_config_does_not_leak_api_key_across_calls(tmp_path, monkeypatch):
    from standup.config import load_config

    cfg_path = tmp_path / ".standup.json"
    cfg_path.write_text(json.dumps({}))
    monkeypatch.setattr("standup.config.CONFIG_PATH", str(cfg_path))

    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "x" * 40)
    first = load_config()
    assert first["provider"]["groq"]["api_key"].startswith("gsk_")

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    second = load_config()
    assert second["provider"]["groq"]["api_key"] == ""


# ---------------------------------------------------------------------------
# save_config
# ---------------------------------------------------------------------------


def test_save_config_writes_json(tmp_path, monkeypatch):
    from standup.security import read_text_restricted

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
            "groq": {"api_key": "", "model": "llama-3.1-8b-instant"},
        },
        "rate_limit": {"cooldown_minutes": 30, "max_calls_per_day": 10, "enabled": True},
    }
    save_config(config)
    data = json.loads(read_text_restricted(str(cfg_path)))
    assert data["tone"] == "casual"
    assert data["provider"]["name"] == "ollama"


def test_save_config_valid_json(tmp_path, monkeypatch):
    from standup.security import read_text_restricted

    cfg_path = tmp_path / ".standup.json"
    monkeypatch.setattr("standup.config.CONFIG_PATH", str(cfg_path))
    save_config(
        {
            "tone": "formal",
            "repos": [],
            "author_email": "",
            "hours_lookback": 24,
            "slack_webhook_url": "",
            "provider": {
                "name": "ollama",
                "ollama": {"base_url": "http://localhost:11434", "model": "llama3"},
                "groq": {"api_key": "", "model": "llama-3.1-8b-instant"},
            },
            "rate_limit": {"cooldown_minutes": 30, "max_calls_per_day": 10, "enabled": True},
        }
    )
    # Should parse without error
    data = json.loads(read_text_restricted(str(cfg_path)))
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
            "groq": {"api_key": "", "model": "llama-3.1-8b-instant"},
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


# ---------------------------------------------------------------------------
# save_config / load_config -- OS keychain integration
# ---------------------------------------------------------------------------


def _fake_keyring(monkeypatch):
    """Monkeypatch keyring with an in-memory store, simulating an
    available OS keychain backend for the duration of a test."""
    import keyring

    store: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(
        keyring,
        "set_password",
        lambda service, key, value: store.__setitem__((service, key), value),
    )
    monkeypatch.setattr(keyring, "get_password", lambda service, key: store.get((service, key)))
    monkeypatch.setattr(
        keyring, "delete_password", lambda service, key: store.pop((service, key), None)
    )
    return store


def test_save_config_scrubs_secrets_from_disk_when_keychain_available(tmp_path, monkeypatch):
    from standup.security import read_text_restricted

    _fake_keyring(monkeypatch)
    cfg_path = tmp_path / ".standup.json"
    monkeypatch.setattr("standup.config.CONFIG_PATH", str(cfg_path))

    config = _valid_config_dict(tmp_path)
    config["provider"]["groq"]["api_key"] = "gsk_realsecret"
    config["slack_webhook_url"] = "https://hooks.slack.com/services/real/webhook/url"

    save_config(config)

    on_disk = json.loads(read_text_restricted(str(cfg_path)))
    assert on_disk["provider"]["groq"]["api_key"] == ""
    assert on_disk["slack_webhook_url"] == ""
    assert config["provider"]["groq"]["api_key"] == "gsk_realsecret"
    assert config["slack_webhook_url"] == "https://hooks.slack.com/services/real/webhook/url"


def test_save_config_keeps_secrets_on_disk_without_a_keychain(tmp_path, monkeypatch):
    from standup.security import read_text_restricted

    monkeypatch.setattr("standup.security.store_secret", lambda _key, _value: False)

    cfg_path = tmp_path / ".standup.json"
    monkeypatch.setattr("standup.config.CONFIG_PATH", str(cfg_path))

    config = _valid_config_dict(tmp_path)
    config["provider"]["groq"]["api_key"] = "gsk_realsecret"

    save_config(config)

    on_disk = json.loads(read_text_restricted(str(cfg_path)))
    assert on_disk["provider"]["groq"]["api_key"] == "gsk_realsecret"


def test_load_config_prefers_keychain_value_over_file(tmp_path, monkeypatch):
    from standup.config import load_config

    store = _fake_keyring(monkeypatch)
    store[("standup-bot", "groq_api_key")] = "gsk_fromkeychain"

    cfg_path = tmp_path / ".standup.json"
    cfg_path.write_text(json.dumps({"provider": {"groq": {"api_key": "gsk_stalefilevalue"}}}))
    monkeypatch.setattr("standup.config.CONFIG_PATH", str(cfg_path))

    config = load_config()
    assert config["provider"]["groq"]["api_key"] == "gsk_fromkeychain"


def test_load_config_env_var_still_wins_over_keychain(tmp_path, monkeypatch):
    from standup.config import load_config

    store = _fake_keyring(monkeypatch)
    store[("standup-bot", "groq_api_key")] = "gsk_fromkeychain"

    cfg_path = tmp_path / ".standup.json"
    cfg_path.write_text(json.dumps({}))
    monkeypatch.setattr("standup.config.CONFIG_PATH", str(cfg_path))
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fromenv" + "x" * 30)

    config = load_config()
    assert config["provider"]["groq"]["api_key"].startswith("gsk_fromenv")


def test_load_config_no_file_uses_defaults(tmp_path, monkeypatch, capsys):
    from standup.config import load_config

    cfg_path = tmp_path / ".standup.json"
    monkeypatch.setattr("standup.config.CONFIG_PATH", str(cfg_path))

    config = load_config()
    assert config["tone"] == "casual"
    assert config["hours_lookback"] == 24
    captured = capsys.readouterr()
    assert "No config found" in captured.out


def test_load_config_oserror_exits(tmp_path, monkeypatch):
    from standup.config import load_config

    cfg_path = tmp_path / ".standup.json"
    cfg_path.write_text("{}")
    monkeypatch.setattr("standup.config.CONFIG_PATH", str(cfg_path))

    def _raise_oserror(*args, **kwargs):
        raise OSError("Permission denied")

    monkeypatch.setattr("standup.security.read_text_restricted", _raise_oserror)

    with pytest.raises(SystemExit):
        load_config()


def test_load_config_webhook_from_keychain(tmp_path, monkeypatch):
    from standup.config import load_config

    store = _fake_keyring(monkeypatch)
    store[("standup-bot", "slack_webhook_url")] = "https://hooks.slack.com/services/test/webhook"

    cfg_path = tmp_path / ".standup.json"
    config_data = _valid_config_dict(tmp_path)
    config_data["slack_webhook_url"] = ""
    cfg_path.write_text(json.dumps(config_data))
    monkeypatch.setattr("standup.config.CONFIG_PATH", str(cfg_path))

    config = load_config()
    assert config["slack_webhook_url"] == "https://hooks.slack.com/services/test/webhook"


def test_load_config_validation_failure_exits(tmp_path, monkeypatch, capsys):
    from standup.config import load_config

    cfg_path = tmp_path / ".standup.json"
    cfg_path.write_text(json.dumps({"tone": "invalid_tone"}))
    monkeypatch.setattr("standup.config.CONFIG_PATH", str(cfg_path))

    with pytest.raises(SystemExit):
        load_config()

    captured = capsys.readouterr()
    assert "Config validation failed" in captured.out


def test_load_config_skips_invalid_repo(tmp_path, monkeypatch, capsys):
    from standup.config import load_config

    cfg_path = tmp_path / ".standup.json"
    non_git_path = tmp_path / "not_a_repo"
    non_git_path.mkdir()
    config_data = _valid_config_dict(tmp_path)
    config_data["repos"] = [str(non_git_path)]
    cfg_path.write_text(json.dumps(config_data))
    monkeypatch.setattr("standup.config.CONFIG_PATH", str(cfg_path))

    config = load_config()
    assert config["repos"] == []
    captured = capsys.readouterr()
    assert "Skipping invalid repo" in captured.out
