"""Tests for standup/logger.py."""

import importlib
import json
import logging
from pathlib import Path

import pytest

from standup import logger as logger_module


def _reset_logger(monkeypatch, tmp_path):
    log_path = tmp_path / ".standup.log"
    importlib.reload(logger_module)
    logging.getLogger(logger_module._LOGGER_NAME).handlers = []
    monkeypatch.setattr(logger_module, "get_log_path", lambda: str(log_path))
    logger_module._LOGGER = None
    return log_path


def _close_logger_handlers():
    logger = logging.getLogger(logger_module._LOGGER_NAME)
    for handler in list(logger.handlers):
        handler.close()
    logger.handlers = []
    logger_module._LOGGER = None


@pytest.fixture(autouse=True)
def _cleanup_logger_fixture():
    yield
    _close_logger_handlers()


def test_logger_creates_file_on_first_call(tmp_path, monkeypatch):
    log_path = _reset_logger(monkeypatch, tmp_path)
    logger = logger_module.get_logger()
    logger.info("{}")
    assert log_path.exists()


def test_log_event_writes_valid_json(tmp_path, monkeypatch):
    log_path = _reset_logger(monkeypatch, tmp_path)
    logger_module.log_event("standup_generated", provider="ollama", commit_count=3)
    payload = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert payload["event"] == "standup_generated"
    assert payload["provider"] == "ollama"
    assert payload["commit_count"] == 3


def test_log_event_redacts_sensitive_keys(tmp_path, monkeypatch):
    log_path = _reset_logger(monkeypatch, tmp_path)
    logger_module.log_event(
        "secret_test",
        api_key="abc",
        secret="def",
        password="ghi",
        token="jkl",
    )
    payload = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert payload["api_key"] == "[REDACTED]"
    assert payload["secret"] == "[REDACTED]"
    assert payload["password"] == "[REDACTED]"
    assert payload["token"] == "[REDACTED]"


def test_multiple_get_logger_calls_return_same_instance(tmp_path, monkeypatch):
    _reset_logger(monkeypatch, tmp_path)
    first = logger_module.get_logger()
    second = logger_module.get_logger()
    assert first is second


def test_log_rotation_creates_backup(tmp_path, monkeypatch):
    log_path = _reset_logger(monkeypatch, tmp_path)
    large_value = "x" * 5000
    for _ in range(260):
        logger_module.log_event("bulk", detail=large_value)
    assert log_path.exists()
    assert Path(str(log_path) + ".1").exists()


def test_log_event_never_raises(monkeypatch, tmp_path):
    _reset_logger(monkeypatch, tmp_path)

    class BrokenLogger:
        def info(self, _message):
            raise RuntimeError("boom")

    monkeypatch.setattr(logger_module, "get_logger", lambda: BrokenLogger())
    logger_module.log_event("safe_failure", provider="ollama")


def test_read_log_entries_returns_tail(tmp_path, monkeypatch):
    _reset_logger(monkeypatch, tmp_path)
    logger_module.log_event("one", provider="ollama")
    logger_module.log_event("two", provider="groq")
    entries = logger_module.read_log_entries(limit=1)
    assert len(entries) == 1
    assert entries[0]["event"] == "two"


def test_clear_logs_truncates_file(tmp_path, monkeypatch):
    log_path = _reset_logger(monkeypatch, tmp_path)
    logger_module.log_event("one", provider="ollama")
    assert logger_module.clear_logs() is True
    assert log_path.read_text(encoding="utf-8") == ""


def test_get_log_size_bytes_zero_when_missing(tmp_path, monkeypatch):
    _reset_logger(monkeypatch, tmp_path)
    assert logger_module.get_log_size_bytes() == 0


def test_rotate_logs_if_needed_returns_false_under_threshold(tmp_path, monkeypatch):
    _reset_logger(monkeypatch, tmp_path)
    logger_module.log_event("tiny", provider="ollama")
    assert logger_module.rotate_logs_if_needed(force_threshold_bytes=10_000) is False


def test_get_log_path_returns_home_path():
    path = logger_module.get_log_path()
    assert path.endswith(".standup.log")


def test_sanitize_exact_sensitive_key_redacts():
    result = logger_module._sanitize_value("commit_message", "fix bug")
    assert result == "[REDACTED]"


def test_sanitize_list_value_passes():
    result = logger_module._sanitize_value("tags", ["a", "b"])
    assert result == ["a", "b"]


def test_sanitize_dict_value_redacts_nested():
    result = logger_module._sanitize_value("details", {"commit_message": "fix", "count": 5})
    assert result["commit_message"] == "[REDACTED]"
    assert result["count"] == 5


def test_read_log_entries_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(logger_module, "get_log_path", lambda: str(tmp_path / "nonexistent.log"))
    entries = logger_module.read_log_entries()
    assert entries == []


def test_read_log_entries_oserror_returns_empty(tmp_path, monkeypatch):
    log_path = tmp_path / "exists.log"
    log_path.write_text("content")
    monkeypatch.setattr(logger_module, "get_log_path", lambda: str(log_path))
    monkeypatch.setattr(Path, "read_text", lambda self, **kw: (_ for _ in ()).throw(OSError()))
    entries = logger_module.read_log_entries()
    assert entries == []


def test_read_log_entries_skips_bad_json_lines(tmp_path, monkeypatch):
    log_path = tmp_path / "mixed.log"
    log_path.write_text('{"event": "good"}\nnot json\n{"event": "also good"}', encoding="utf-8")
    monkeypatch.setattr(logger_module, "get_log_path", lambda: str(log_path))
    entries = logger_module.read_log_entries(limit=10)
    assert len(entries) == 2
    assert entries[0]["event"] == "good"
    assert entries[1]["event"] == "also good"


def test_clear_logs_oserror_returns_false(tmp_path, monkeypatch):
    _reset_logger(monkeypatch, tmp_path)
    logger_module.log_event("test", value=1)
    monkeypatch.setattr(Path, "write_text", lambda self, *a, **kw: (_ for _ in ()).throw(OSError()))
    result = logger_module.clear_logs()
    assert result is False


def test_get_logger_handler_creation_failure(monkeypatch, tmp_path):
    import logging.handlers

    def broken_handler(*args, **kwargs):
        raise Exception("handler creation failed")

    monkeypatch.setattr(logging.handlers, "RotatingFileHandler", broken_handler)
    _reset_logger(monkeypatch, tmp_path)
    logger = logger_module.get_logger()
    assert any(isinstance(h, logging.NullHandler) for h in logger.handlers)


def test_enforce_permissions_oserror_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr("standup.logger.os.name", "posix")
    test_file = tmp_path / "test.log"
    test_file.write_text("content")

    class FakeStat:
        st_mode = 0o644

    monkeypatch.setattr(Path, "stat", lambda self, *a, **kw: FakeStat())
    monkeypatch.setattr(
        Path, "chmod", lambda self, mode: (_ for _ in ()).throw(OSError("chmod failed"))
    )
    logger_module._enforce_permissions(str(test_file))


def test_rotate_logs_if_needed_success(tmp_path, monkeypatch):
    log_path = _reset_logger(monkeypatch, tmp_path)
    logger_module.get_logger()
    log_path.write_text("x" * 600_000, encoding="utf-8")
    result = logger_module.rotate_logs_if_needed()
    assert result is True


def test_rotate_logs_if_needed_rollover_exception(tmp_path, monkeypatch):
    log_path = _reset_logger(monkeypatch, tmp_path)
    logger = logger_module.get_logger()
    log_path.write_text("x" * 600_000, encoding="utf-8")
    handler = logger.handlers[0]
    monkeypatch.setattr(
        handler, "doRollover", lambda: (_ for _ in ()).throw(Exception("rollover failed"))
    )
    result = logger_module.rotate_logs_if_needed()
    assert result is False


def test_rotate_logs_if_needed_no_rotating_handler(tmp_path, monkeypatch):
    log_path = _reset_logger(monkeypatch, tmp_path)
    logger = logger_module.get_logger()
    logger.handlers = [logging.StreamHandler()]
    log_path.write_text("x" * 600_000, encoding="utf-8")
    result = logger_module.rotate_logs_if_needed()
    assert result is False
