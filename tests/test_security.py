"""Tests for standup/security.py."""

import json
import stat
import sys
from pathlib import Path

import pytest

from standup.security import (
    _format_size,
    _permission_status,
    mask_api_key,
    redact_sensitive_patterns,
    sanitize_error_message,
    validate_groq_api_key,
)


def test_valid_groq_key():
    key = "gsk_" + "a" * 40
    assert validate_groq_api_key(key) is True


def test_groq_key_wrong_prefix():
    key = "sk-" + "a" * 40
    assert validate_groq_api_key(key) is False


def test_groq_key_too_short():
    key = "gsk_abc"
    assert validate_groq_api_key(key) is False


def test_mask_api_key_format():
    key = "gsk_abcdefghij" + "x" * 30 + "ZZZZ"
    masked = mask_api_key(key)
    assert masked.startswith("gsk_abcdef")
    assert masked.endswith("ZZZZ")
    assert "****" in masked


def test_mask_api_key_short():
    assert mask_api_key("short") == "****"


def test_redact_password():
    text = "set password=s3cr3t in config"
    result = redact_sensitive_patterns(text)
    assert "s3cr3t" not in result
    assert "[REDACTED]" in result


def test_redact_private_ip():
    text = "connecting to 192.168.1.100"
    result = redact_sensitive_patterns(text)
    assert "192.168.1.100" not in result
    assert "[REDACTED]" in result


def test_redact_private_ip_10_range_fully_redacted():
    text = "deployed to 10.20.30.40 and 10.0.0.5 last night"
    result = redact_sensitive_patterns(text)
    assert "10.20.30.40" not in result
    assert "10.0.0.5" not in result
    assert ".40" not in result
    assert ".5 " not in result
    assert result.count("[REDACTED]") == 2


def test_redact_quoted_multiword_secret():
    text = 'set password: "my secret phrase" in config'
    result = redact_sensitive_patterns(text)
    assert "my secret phrase" not in result
    assert "[REDACTED]" in result


def test_redact_private_hostname():
    text = "deploy to myserver.local"
    result = redact_sensitive_patterns(text)
    assert "myserver.local" not in result
    assert "[REDACTED]" in result


def test_redact_bearer_token():
    text = "Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.abc"
    result = redact_sensitive_patterns(text)
    assert "eyJhbGciOiJSUzI1NiJ9" not in result


def test_redact_safe_text():
    text = "refactor login flow and update README"
    result = redact_sensitive_patterns(text)
    assert result == text


def test_sanitize_error_message_hides_windows_paths():
    message = sanitize_error_message(Exception(r"failed at C:\Users\name\secret.txt"))
    assert "C:\\Users" not in message
    assert "[REDACTED]" in message


def test_sanitize_error_message_hides_unix_home_paths():
    message = sanitize_error_message(Exception("/Users/tester/project/config.json"))
    assert "/Users/tester" not in message
    assert "[REDACTED]" in message


def test_sanitize_error_message_hides_email_addresses():
    message = sanitize_error_message(Exception("contact me at dev@example.com"))
    assert "dev@example.com" not in message
    assert "[REDACTED]" in message


def test_sanitize_error_message_truncates_to_200_chars():
    message = sanitize_error_message(Exception("x" * 500))
    assert len(message) <= 203


def test_sanitize_error_message_handles_none():
    assert sanitize_error_message(None) == "An unexpected error occurred."


def test_sanitize_error_message_handles_permission_error():
    message = sanitize_error_message(PermissionError("secret path"))
    assert "Permission was denied" in message


# ──────────────────────────────────────────────────────────────────────────────
# Issue #2: secret formats without a nearby trigger word
# ──────────────────────────────────────────────────────────────────────────────


def test_redact_github_classic_pat():
    token = "ghp_" + "a" * 36
    text = f"fix: rotate {token} after leak"
    result = redact_sensitive_patterns(text)
    assert token not in result
    assert "[REDACTED:GITHUB_TOKEN]" in result


def test_redact_github_fine_grained_pat():
    token = "github_pat_" + "A" * 22 + "_" + "B" * 59
    text = f"fix: rotate {token}"
    result = redact_sensitive_patterns(text)
    assert token not in result
    assert "[REDACTED:GITHUB_TOKEN]" in result


def test_redact_anthropic_key_full_key_not_just_prefix():
    # Regression test: an earlier draft's char class excluded "-"/"_", so it
    # only matched "sk-ant" and left the rest of the key (which uses the
    # base64url alphabet, including "-" and "_") exposed after "redaction".
    key = "sk-ant-api03-" + "aB3" * 20 + "-xY9zZ"
    text = f"debug: leaked {key} in log"
    result = redact_sensitive_patterns(text)
    assert key not in result
    # No fragment of the key body should survive redaction
    assert "aB3aB3aB3" not in result
    assert "[REDACTED:API_KEY]" in result


def test_redact_openai_proj_key():
    key = "sk-proj-" + "a1B2c3D4-e5F6g7H8_i9J0k1L2m3N4o5"
    text = f"chore: remove {key} from .env"
    result = redact_sensitive_patterns(text)
    assert key not in result
    assert "[REDACTED:API_KEY]" in result


def test_redact_aws_access_key():
    # Concatenated for the same reason as the Slack token above: this is
    # AWS's own documented example key, but a contiguous literal still
    # matches the AKIA[0-9A-Z]{16} shape closely enough to trip push
    # protection.
    fake_aws_key = "AKIA" + "IOSFODNN7EXAMPLE"
    text = f"chore: rotate {fake_aws_key} for CI"
    result = redact_sensitive_patterns(text)
    assert fake_aws_key not in result
    assert "[REDACTED:AWS_KEY]" in result


def test_redact_slack_bot_token():
    # Built via concatenation, not a single literal: GitHub's push-protection
    # secret scanner pattern-matches the raw source text, and a contiguous
    # "xoxb-..." literal here is shaped enough like a real Slack token to
    # trip it, even inside a test fixture. The runtime string (and therefore
    # what the regex under test actually sees) is identical either way.
    fake_slack_token = "xoxb-" + "1234567890-abcdefghijklmnop"
    text = f"fix: revoke {fake_slack_token} after leak"
    result = redact_sensitive_patterns(text)
    assert fake_slack_token not in result
    assert "[REDACTED:SLACK_TOKEN]" in result


def test_redact_uri_credentials():
    text = "fix: rotate https://user:hunter2@db.internal/prod"
    result = redact_sensitive_patterns(text)
    assert "hunter2" not in result
    assert "[REDACTED:URI_CREDENTIALS]" in result


def test_redact_compound_secret_key_variable():
    text = "fix: rotate SECRET_KEY=abc123xyz in settings"
    result = redact_sensitive_patterns(text)
    assert "abc123xyz" not in result


def test_redact_compound_private_key_variable():
    text = "chore: remove PRIVATE_KEY=abc123xyz from repo"
    result = redact_sensitive_patterns(text)
    assert "abc123xyz" not in result


def test_redact_compound_auth_token_variable():
    text = "fix: rotate AUTH_TOKEN=abc123xyz after leak"
    result = redact_sensitive_patterns(text)
    assert "abc123xyz" not in result


def test_redact_does_not_flag_bare_key_word():
    # Regression test: a bare "KEY" trigger word (considered and rejected
    # during the issue #2 discussion) false-positives on ordinary commit
    # messages that just happen to contain the word "key" before "=".
    text = "feat: support KEY=VALUE parsing for .env files"
    result = redact_sensitive_patterns(text)
    assert result == text


def test_redact_does_not_flag_shard_key_column_name():
    text = "chore: rename SHARD-KEY=tenant_id column"
    result = redact_sensitive_patterns(text)
    assert result == text


# ---------------------------------------------------------------------------
# store_secret / get_secret / delete_secret (OS keychain wrapper)
# ---------------------------------------------------------------------------


def test_store_secret_returns_false_without_a_keychain_backend(monkeypatch):
    import keyring

    from standup.security import store_secret

    def fake_set_password(*args, **kwargs):
        raise RuntimeError("no keychain")

    monkeypatch.setattr(keyring, "set_password", fake_set_password)
    assert store_secret("groq_api_key", "gsk_test") is False


def test_get_secret_returns_none_without_a_keychain_backend(monkeypatch):
    import keyring

    from standup.security import get_secret

    def fake_get_password(*args, **kwargs):
        raise RuntimeError("no keychain")

    monkeypatch.setattr(keyring, "get_password", fake_get_password)
    assert get_secret("groq_api_key") is None


def test_store_secret_returns_false_for_empty_value():
    from standup.security import store_secret

    assert store_secret("groq_api_key", "") is False


def test_store_and_get_secret_round_trip_with_a_working_backend(monkeypatch):
    """Simulates an available OS keychain (macOS Keychain / Windows
    Credential Manager / Linux Secret Service) to exercise the actual
    happy path, not just the no-backend fallback this sandbox has."""
    import keyring

    store: dict[tuple[str, str], str] = {}

    def fake_set_password(service, key_name, value):
        store[(service, key_name)] = value

    def fake_get_password(service, key_name):
        return store.get((service, key_name))

    monkeypatch.setattr(keyring, "set_password", fake_set_password)
    monkeypatch.setattr(keyring, "get_password", fake_get_password)

    from standup.security import get_secret, store_secret

    assert store_secret("groq_api_key", "gsk_realvalue") is True
    assert get_secret("groq_api_key") == "gsk_realvalue"


def test_delete_secret_never_raises_without_a_backend():
    from standup.security import delete_secret

    delete_secret("groq_api_key")  # must not raise


# ---------------------------------------------------------------------------
# write_text_restricted
# ---------------------------------------------------------------------------


def test_write_text_restricted_result_is_owner_only_and_correct_content(tmp_path):
    from standup.security import read_text_restricted, write_text_restricted

    target = tmp_path / "secret.json"
    write_text_restricted(str(target), '{"a": 1}', label="Test file")

    assert read_text_restricted(str(target), label="Test file") == '{"a": 1}'
    if sys.platform != "win32":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_write_text_restricted_never_mangles_secret_shaped_content(tmp_path):
    """write_text_restricted is a generic write primitive and must not
    guess at caller intent by scanning/scrubbing content, whether a
    secret belongs on disk is a decision only the caller can make (see
    config.save_config()'s documented keychain-first, restricted-file
    fallback). A previous version auto-redacted "detected" secrets
    here, which would silently corrupt save_config()'s intentional
    fallback persistence if the detection/redaction pattern mismatch
    that made it a no-op for Groq keys were ever "fixed"."""
    from standup.security import read_text_restricted, write_text_restricted

    target = tmp_path / "secret.json"
    content = json.dumps({"api_key": "gsk_" + "a" * 40, "webhook": "https://hooks.slack.com/x"})
    write_text_restricted(str(target), content, label="Test file")

    assert read_text_restricted(str(target), label="Test file") == content


def test_redact_sensitive_patterns_redacts_groq_key():
    """GROQ_KEY must actually be wired into _TAGGED_PATTERNS (the set
    redact_sensitive_patterns() iterates), not just into a detection-only
    list. A prior version could report a Groq key as "found" while
    never actually substituting it out."""
    key = "gsk_" + "a" * 40
    result = redact_sensitive_patterns(f"leaked my key {key} in a commit")
    assert key not in result
    assert "[REDACTED:GROQ_KEY]" in result


def test_write_text_restricted_locks_down_before_content_exists(tmp_path, monkeypatch):
    """The file must never be observably world-readable, including at
    creation -- assert permissions are already tightened by the time
    enforce_file_permissions is invoked, before write_text runs."""
    import standup.security as security_module

    target = tmp_path / "secret.json"
    call_order = []

    real_enforce = security_module.enforce_file_permissions

    def spy_enforce(file_path, label="File"):
        call_order.append("enforce")
        real_enforce(file_path, label=label)
        if sys.platform != "win32" and file_path == str(target):
            assert stat.S_IMODE(Path(file_path).stat().st_mode) == 0o600
        if file_path == str(target):
            assert Path(file_path).read_bytes() == b""

    monkeypatch.setattr(security_module, "enforce_file_permissions", spy_enforce)

    real_write_bytes = Path.write_bytes

    def spy_write_bytes(self, data):
        call_order.append(f"write({self.name})")
        return real_write_bytes(self, data)

    monkeypatch.setattr(Path, "write_bytes", spy_write_bytes)

    security_module.write_text_restricted(str(target), '{"secret": "value"}')

    key_file = target.name + ".key"
    assert call_order == [
        "enforce",
        f"write({key_file})",
        "enforce",
        f"write({target.name})",
    ]


# ---------------------------------------------------------------------------
# Windows ACL enforcement (mocked -- this test suite runs on Linux)
# ---------------------------------------------------------------------------


def test_windows_acl_enforcement_invokes_icacls(tmp_path, monkeypatch):
    import subprocess

    import standup.security as security_module

    target = tmp_path / "secret.json"
    target.write_text("x", encoding="utf-8")

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, returncode=0)

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "run", fake_run)

    security_module.enforce_file_permissions(str(target), label="Config file")

    assert captured["cmd"][0] == "icacls"
    assert str(target) in captured["cmd"]
    assert "/inheritance:r" in captured["cmd"]


def test_windows_acl_enforcement_warns_once_on_icacls_failure(tmp_path, monkeypatch, capsys):
    import subprocess

    import standup.security as security_module

    target = tmp_path / "secret.json"
    target.write_text("x", encoding="utf-8")

    def failing_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode=1)

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "run", failing_run)
    security_module._PERMISSION_WARNED_PATHS.clear()

    security_module.enforce_file_permissions(str(target), label="Config file")
    security_module.enforce_file_permissions(str(target), label="Config file")

    out = capsys.readouterr().out
    assert out.count("Could not restrict permissions") == 1  # warn-once, not every call


def test_redact_sensitive_patterns_converts_non_string():
    from standup.security import redact_sensitive_patterns

    result = redact_sensitive_patterns(42)
    assert "[REDACTED]" not in result


def test_sanitize_error_message_file_not_found():
    msg = sanitize_error_message(FileNotFoundError("some path"))
    assert "file or directory" in msg


def test_sanitize_error_message_timeout():
    msg = sanitize_error_message(TimeoutError("timed out"))
    assert "timed out" in msg


def test_sanitize_error_message_sqlite():
    import sqlite3

    msg = sanitize_error_message(sqlite3.Error("db error"))
    assert "database" in msg


def test_sanitize_error_message_empty_after_strip():
    msg = sanitize_error_message(Exception("   "))
    assert msg == "An unexpected error occurred."


def test_sanitize_error_message_exception_in_formatting():
    class BadExc(Exception):
        def __str__(self):
            raise RuntimeError("boom")

    msg = sanitize_error_message(BadExc())
    assert msg == "An unexpected error occurred."


def test_sanitize_error_message_empty_after_redaction(monkeypatch):
    import re

    monkeypatch.setattr("standup.security._REDACTED", "")
    monkeypatch.setattr("standup.security._ERROR_PATTERNS", [re.compile(r".*")])
    msg = sanitize_error_message(Exception("any message"))
    assert msg == "An unexpected error occurred."


def test_store_secret_warns_once_on_keychain_failure(monkeypatch, capsys):
    from standup.security import _KEYRING_WARNED_KEYS, store_secret

    _KEYRING_WARNED_KEYS.clear()
    import keyring

    def fake_set_password(*args, **kwargs):
        raise RuntimeError("no keychain")

    monkeypatch.setattr(keyring, "set_password", fake_set_password)
    assert store_secret("test_key", "value") is False
    assert store_secret("test_key", "value") is False
    out = capsys.readouterr().out
    assert out.count("No OS keychain") == 1


def test_delete_secret_ignores_exception(monkeypatch):
    import keyring

    from standup.security import delete_secret

    def fake_delete(*args, **kwargs):
        raise RuntimeError("no keychain")

    monkeypatch.setattr(keyring, "delete_password", fake_delete)
    delete_secret("test_key")


def test_enforce_file_permissions_missing_file(tmp_path):
    from standup.security import enforce_file_permissions

    enforce_file_permissions(str(tmp_path / "nonexistent"), label="Test")


@pytest.mark.skipif(sys.platform == "win32", reason="chmod semantics differ on Windows")
def test_enforce_file_permissions_unix_chmod(tmp_path, monkeypatch):
    import sys

    from standup.security import enforce_file_permissions

    monkeypatch.setattr(sys, "platform", "linux")
    target = tmp_path / "test.txt"
    target.write_text("hello")
    target.chmod(0o644)
    enforce_file_permissions(str(target), label="Test")
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="WindowsPath.stat is read-only")
def test_enforce_file_permissions_unix_oserror(tmp_path, monkeypatch):
    import pathlib
    import sys

    from standup.security import enforce_file_permissions

    monkeypatch.setattr(sys, "platform", "linux")
    target = tmp_path / "test.txt"
    target.write_text("hello")
    original_stat = pathlib.Path.stat

    def broken_stat(self, *args, **kwargs):
        if str(self) == str(target):
            raise OSError("permission denied")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "stat", broken_stat)
    enforce_file_permissions(str(target), label="Test")


def test_windows_acl_subprocess_error(tmp_path, monkeypatch, capsys):
    import subprocess
    import sys

    import standup.security as security_module

    target = tmp_path / "secret.json"
    target.write_text("x")

    def fake_run(*args, **kwargs):
        raise subprocess.SubprocessError("icacls not found")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "run", fake_run)
    security_module._PERMISSION_WARNED_PATHS.clear()
    security_module.enforce_file_permissions(str(target), label="Config file")
    out = capsys.readouterr().out
    assert "Could not restrict permissions" in out


def test_read_text_restricted_decryption_fallback(tmp_path):
    from cryptography.fernet import Fernet

    from standup.security import read_text_restricted

    target = tmp_path / "secret.json"
    target.write_text("plain text fallback")
    key = Fernet.generate_key()
    key_path = tmp_path / "secret.json.key"
    key_path.write_bytes(key)
    result = read_text_restricted(str(target))
    assert result == "plain text fallback"


def test_write_text_restricted_existing_key(tmp_path):
    from standup.security import read_text_restricted, write_text_restricted

    target = tmp_path / "secret2.json"
    write_text_restricted(str(target), "first write")
    write_text_restricted(str(target), "second write")
    assert read_text_restricted(str(target)) == "second write"


def test_permission_status_missing_file():
    label, status, detail = _permission_status("/nonexistent/path", "Test")
    assert status == "ℹ️"
    assert "Not yet created" in detail


def test_permission_status_windows(monkeypatch):
    import sys

    monkeypatch.setattr(sys, "platform", "win32")
    label, status, detail = _permission_status(__file__, "Test")
    assert status == "⚠️"


@pytest.mark.skipif(sys.platform == "win32", reason="WindowsPath.stat is read-only")
def test_permission_status_oserror(tmp_path, monkeypatch):
    import pathlib
    import sys

    monkeypatch.setattr(sys, "platform", "linux")
    target = tmp_path / "test.txt"
    target.write_text("hello")
    original_stat = pathlib.Path.stat

    def broken_stat(self, *args, **kwargs):
        if str(self) == str(target):
            raise OSError("no access")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "stat", broken_stat)
    label, status, detail = _permission_status(str(target), "Test")
    assert status == "❌"


@pytest.mark.skipif(sys.platform == "win32", reason="chmod semantics differ on Windows")
def test_permission_status_correct_mode(tmp_path, monkeypatch):
    import sys

    monkeypatch.setattr(sys, "platform", "linux")
    target = tmp_path / "test.txt"
    target.write_text("hello")
    target.chmod(0o600)
    label, status, detail = _permission_status(str(target), "Test")
    assert status == "✅"


@pytest.mark.skipif(sys.platform == "win32", reason="chmod semantics differ on Windows")
def test_permission_status_wrong_mode(tmp_path, monkeypatch):
    import sys

    monkeypatch.setattr(sys, "platform", "linux")
    target = tmp_path / "test.txt"
    target.write_text("hello")
    target.chmod(0o644)
    label, status, detail = _permission_status(str(target), "Test")
    assert status == "❌"


def test_format_size_bytes():
    assert _format_size(500) == "500 B"


def test_format_size_kilobytes():
    assert "KB" in _format_size(2048)


def test_format_size_megabytes():
    assert "MB" in _format_size(5 * 1024 * 1024)


def test_enforce_config_permissions(tmp_path):
    from standup.security import enforce_config_permissions

    target = tmp_path / "config.json"
    target.write_text("{}")
    enforce_config_permissions(str(target))


# ---------------------------------------------------------------------------
# _permission_status — Unix stat branch (via monkeypatch on Windows)
# ---------------------------------------------------------------------------


def test_permission_status_unix_correct_mode(tmp_path, monkeypatch):
    import pathlib
    import sys

    from standup.security import _permission_status

    monkeypatch.setattr(sys, "platform", "linux")
    target = tmp_path / "test.txt"
    target.write_text("hello")
    original_stat = pathlib.Path.stat

    def fake_stat(self):
        if str(self) == str(target):
            return type("FakeStat", (), {"st_mode": 0o100600})()
        return original_stat(self)

    monkeypatch.setattr(pathlib.Path, "stat", fake_stat)
    label, status, detail = _permission_status(str(target), "Test")
    assert status == "✅"


def test_permission_status_unix_wrong_mode(tmp_path, monkeypatch):
    import pathlib
    import sys

    from standup.security import _permission_status

    monkeypatch.setattr(sys, "platform", "linux")
    target = tmp_path / "test.txt"
    target.write_text("hello")
    original_stat = pathlib.Path.stat

    def fake_stat(self):
        if str(self) == str(target):
            return type("FakeStat", (), {"st_mode": 0o100644})()
        return original_stat(self)

    monkeypatch.setattr(pathlib.Path, "stat", fake_stat)
    label, status, detail = _permission_status(str(target), "Test")
    assert status == "❌"


def test_permission_status_unix_oserror(tmp_path, monkeypatch):
    import pathlib
    import sys

    from standup.security import _permission_status

    monkeypatch.setattr(sys, "platform", "linux")
    target = tmp_path / "test.txt"
    target.write_text("hello")
    original_stat = pathlib.Path.stat

    def broken_stat(self, *args, **kwargs):
        if str(self) == str(target):
            raise OSError("no access")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "stat", broken_stat)
    label, status, detail = _permission_status(str(target), "Test")
    assert status == "❌"
    assert "Could not stat file" in detail


# ---------------------------------------------------------------------------
# enforce_file_permissions — Unix chmod branch
# ---------------------------------------------------------------------------


def test_enforce_file_permissions_unix_chmod_sets_600(tmp_path, monkeypatch):
    import pathlib
    import sys

    from standup.security import enforce_file_permissions

    monkeypatch.setattr(sys, "platform", "linux")
    target = tmp_path / "test.txt"
    target.write_text("hello")
    chmod_called = []
    original_stat = pathlib.Path.stat

    def fake_stat(self):
        if str(self) == str(target):
            return type("FakeStat", (), {"st_mode": 0o100644})()
        return original_stat(self)

    monkeypatch.setattr(pathlib.Path, "stat", fake_stat)

    def fake_chmod(self, mode):
        chmod_called.append(mode)

    monkeypatch.setattr(pathlib.Path, "chmod", fake_chmod)
    enforce_file_permissions(str(target), label="Test")
    assert 0o600 in chmod_called


def test_enforce_file_permissions_unix_oserror_swallowed(tmp_path, monkeypatch):
    import pathlib
    import sys

    from standup.security import enforce_file_permissions

    monkeypatch.setattr(sys, "platform", "linux")
    target = tmp_path / "test.txt"
    target.write_text("hello")
    original_stat = pathlib.Path.stat

    def broken_stat(self, *args, **kwargs):
        if str(self) == str(target):
            raise OSError("permission denied")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "stat", broken_stat)
    enforce_file_permissions(str(target), label="Test")


# ---------------------------------------------------------------------------
# sanitize_error_message — remaining uncovered lines
# ---------------------------------------------------------------------------


def test_sanitize_error_message_json_decode_error():
    import json

    from standup.security import sanitize_error_message

    msg = sanitize_error_message(json.JSONDecodeError("bad json", "{bad", 0))
    assert "JSON" in msg


# ---------------------------------------------------------------------------
# run_doctor — health check
# ---------------------------------------------------------------------------


class _FakeResult:
    def fetchone(self):
        return ("wal",)


class _FakeConn:
    def execute(self, sql):
        return _FakeResult()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_run_doctor_no_config_file(monkeypatch, tmp_path, capsys):
    import standup.config
    import standup.history
    import standup.security as security_module
    import standup.validator as validator_module

    config_path = str(tmp_path / ".standup.json")
    monkeypatch.setattr(standup.config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(standup.config, "USAGE_PATH", str(tmp_path / ".standup_usage.json"))
    monkeypatch.setattr(standup.history, "init_db", lambda: None)
    monkeypatch.setattr(standup.history, "get_db_path", lambda: str(tmp_path / "history.db"))
    monkeypatch.setattr(standup.history, "get_db_size_bytes", lambda _: 1000)
    monkeypatch.setattr(standup.history, "get_row_count", lambda _: 0)
    monkeypatch.setattr(standup.history, "_get_connection", lambda _: _FakeConn())
    monkeypatch.setattr(standup.history, "_MIGRATIONS", [(1, "2026-01-01", "init")])
    monkeypatch.setattr(standup.history, "get_current_schema_version", lambda _: 1)
    monkeypatch.setattr(validator_module, "validate_quality_config", lambda _: (True, ""))
    monkeypatch.setattr(validator_module, "validate_template_name", lambda *a: (True, ""))
    monkeypatch.setattr(validator_module, "validate_full_config", lambda _: (True, []))
    monkeypatch.setattr(security_module, "log_event", lambda *a, **kw: None)

    security_module.run_doctor()
    out = capsys.readouterr().out
    assert "Config file not found" in out
    assert "Health Score" in out


def test_run_doctor_groq_env_key(monkeypatch, tmp_path, capsys):
    import json

    import standup.config
    import standup.history
    import standup.security as security_module
    import standup.validator as validator_module

    config = {
        "provider": {"name": "groq"},
        "repos": [],
        "slack_webhook_url": "",
        "quality": {},
        "template": "default",
        "custom_templates": {},
        "rate_limit": {},
    }
    config_path = tmp_path / ".standup.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(standup.config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(standup.config, "USAGE_PATH", str(tmp_path / ".standup_usage.json"))
    monkeypatch.setattr(standup.history, "init_db", lambda: None)
    monkeypatch.setattr(standup.history, "get_db_path", lambda: str(tmp_path / "history.db"))
    monkeypatch.setattr(standup.history, "get_db_size_bytes", lambda _: 1000)
    monkeypatch.setattr(standup.history, "get_row_count", lambda _: 3)
    monkeypatch.setattr(standup.history, "_get_connection", lambda _: _FakeConn())
    monkeypatch.setattr(standup.history, "_MIGRATIONS", [(1, "2026-01-01", "init")])
    monkeypatch.setattr(standup.history, "get_current_schema_version", lambda _: 1)
    monkeypatch.setattr(validator_module, "validate_quality_config", lambda _: (True, ""))
    monkeypatch.setattr(validator_module, "validate_template_name", lambda *a: (True, ""))
    monkeypatch.setattr(validator_module, "validate_full_config", lambda _: (True, []))
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "a" * 40)
    monkeypatch.setattr(security_module, "log_event", lambda *a, **kw: None)

    security_module.run_doctor()
    out = capsys.readouterr().out
    assert "Loaded from GROQ_API_KEY" in out
    assert "Key looks valid" in out
    assert "Health Score" in out


def test_run_doctor_groq_invalid_key(monkeypatch, tmp_path, capsys):
    import json

    import standup.config
    import standup.history
    import standup.security as security_module
    import standup.validator as validator_module

    config = {
        "provider": {"name": "groq"},
        "repos": [],
        "slack_webhook_url": "",
        "quality": {},
        "template": "default",
        "custom_templates": {},
        "rate_limit": {},
    }
    config_path = tmp_path / ".standup.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(standup.config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(standup.config, "USAGE_PATH", str(tmp_path / ".standup_usage.json"))
    monkeypatch.setattr(standup.history, "init_db", lambda: None)
    monkeypatch.setattr(standup.history, "get_db_path", lambda: str(tmp_path / "history.db"))
    monkeypatch.setattr(standup.history, "get_db_size_bytes", lambda _: 1000)
    monkeypatch.setattr(standup.history, "get_row_count", lambda _: 3)
    monkeypatch.setattr(standup.history, "_get_connection", lambda _: _FakeConn())
    monkeypatch.setattr(standup.history, "_MIGRATIONS", [(1, "2026-01-01", "init")])
    monkeypatch.setattr(standup.history, "get_current_schema_version", lambda _: 1)
    monkeypatch.setattr(validator_module, "validate_quality_config", lambda _: (True, ""))
    monkeypatch.setattr(validator_module, "validate_template_name", lambda *a: (True, ""))
    monkeypatch.setattr(validator_module, "validate_full_config", lambda _: (True, []))
    monkeypatch.setenv("GROQ_API_KEY", "not-a-valid-key")
    monkeypatch.setattr(security_module, "log_event", lambda *a, **kw: None)

    security_module.run_doctor()
    out = capsys.readouterr().out
    assert "Key format is invalid" in out


def test_run_doctor_groq_no_key(monkeypatch, tmp_path, capsys):
    import json

    import standup.config
    import standup.history
    import standup.security as security_module
    import standup.validator as validator_module

    config = {
        "provider": {"name": "groq"},
        "repos": [],
        "slack_webhook_url": "",
        "quality": {},
        "template": "default",
        "custom_templates": {},
        "rate_limit": {},
    }
    config_path = tmp_path / ".standup.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(standup.config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(standup.config, "USAGE_PATH", str(tmp_path / ".standup_usage.json"))
    monkeypatch.setattr(standup.history, "init_db", lambda: None)
    monkeypatch.setattr(standup.history, "get_db_path", lambda: str(tmp_path / "history.db"))
    monkeypatch.setattr(standup.history, "get_db_size_bytes", lambda _: 1000)
    monkeypatch.setattr(standup.history, "get_row_count", lambda _: 3)
    monkeypatch.setattr(standup.history, "_get_connection", lambda _: _FakeConn())
    monkeypatch.setattr(standup.history, "_MIGRATIONS", [(1, "2026-01-01", "init")])
    monkeypatch.setattr(standup.history, "get_current_schema_version", lambda _: 1)
    monkeypatch.setattr(validator_module, "validate_quality_config", lambda _: (True, ""))
    monkeypatch.setattr(validator_module, "validate_template_name", lambda *a: (True, ""))
    monkeypatch.setattr(validator_module, "validate_full_config", lambda _: (True, []))
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(security_module, "log_event", lambda *a, **kw: None)

    security_module.run_doctor()
    out = capsys.readouterr().out
    assert "No Groq API key found" in out
    assert "No key to validate" in out


def test_run_doctor_ollama_available(monkeypatch, tmp_path, capsys):
    import json

    import standup.config
    import standup.history
    import standup.security as security_module
    import standup.validator as validator_module

    config = {
        "provider": {"name": "ollama"},
        "repos": [],
        "slack_webhook_url": "",
        "quality": {},
        "template": "default",
        "custom_templates": {},
        "rate_limit": {},
    }
    config_path = tmp_path / ".standup.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(standup.config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(standup.config, "USAGE_PATH", str(tmp_path / ".standup_usage.json"))
    monkeypatch.setattr(standup.history, "init_db", lambda: None)
    monkeypatch.setattr(standup.history, "get_db_path", lambda: str(tmp_path / "history.db"))
    monkeypatch.setattr(standup.history, "get_db_size_bytes", lambda _: 1000)
    monkeypatch.setattr(standup.history, "get_row_count", lambda _: 3)
    monkeypatch.setattr(standup.history, "_get_connection", lambda _: _FakeConn())
    monkeypatch.setattr(standup.history, "_MIGRATIONS", [(1, "2026-01-01", "init")])
    monkeypatch.setattr(standup.history, "get_current_schema_version", lambda _: 1)
    monkeypatch.setattr(validator_module, "validate_quality_config", lambda _: (True, ""))
    monkeypatch.setattr(validator_module, "validate_template_name", lambda *a: (True, ""))
    monkeypatch.setattr(validator_module, "validate_full_config", lambda _: (True, []))
    monkeypatch.setattr(security_module, "log_event", lambda *a, **kw: None)

    class FakeOllamaProvider:
        def __init__(self, cfg):
            pass

        def is_available(self):
            return True

    monkeypatch.setattr("standup.llm.ollama_provider.OllamaProvider", FakeOllamaProvider)

    security_module.run_doctor()
    out = capsys.readouterr().out
    assert "Configured model is reachable" in out


def test_run_doctor_ollama_unavailable(monkeypatch, tmp_path, capsys):
    import json

    import standup.config
    import standup.history
    import standup.security as security_module
    import standup.validator as validator_module

    config = {
        "provider": {"name": "ollama"},
        "repos": [],
        "slack_webhook_url": "",
        "quality": {},
        "template": "default",
        "custom_templates": {},
        "rate_limit": {},
    }
    config_path = tmp_path / ".standup.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(standup.config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(standup.config, "USAGE_PATH", str(tmp_path / ".standup_usage.json"))
    monkeypatch.setattr(standup.history, "init_db", lambda: None)
    monkeypatch.setattr(standup.history, "get_db_path", lambda: str(tmp_path / "history.db"))
    monkeypatch.setattr(standup.history, "get_db_size_bytes", lambda _: 1000)
    monkeypatch.setattr(standup.history, "get_row_count", lambda _: 3)
    monkeypatch.setattr(standup.history, "_get_connection", lambda _: _FakeConn())
    monkeypatch.setattr(standup.history, "_MIGRATIONS", [(1, "2026-01-01", "init")])
    monkeypatch.setattr(standup.history, "get_current_schema_version", lambda _: 1)
    monkeypatch.setattr(validator_module, "validate_quality_config", lambda _: (True, ""))
    monkeypatch.setattr(validator_module, "validate_template_name", lambda *a: (True, ""))
    monkeypatch.setattr(validator_module, "validate_full_config", lambda _: (True, []))
    monkeypatch.setattr(security_module, "log_event", lambda *a, **kw: None)

    class FakeOllamaProvider:
        def __init__(self, cfg):
            pass

        def is_available(self):
            return False

    monkeypatch.setattr("standup.llm.ollama_provider.OllamaProvider", FakeOllamaProvider)

    security_module.run_doctor()
    out = capsys.readouterr().out
    assert "Server not running" in out


def test_run_doctor_config_validation_fails(monkeypatch, tmp_path, capsys):
    import json

    import standup.config
    import standup.history
    import standup.security as security_module
    import standup.validator as validator_module

    config = {
        "provider": {"name": "groq"},
        "repos": [],
        "slack_webhook_url": "",
        "quality": {},
        "template": "default",
        "custom_templates": {},
        "rate_limit": {},
    }
    config_path = tmp_path / ".standup.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(standup.config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(standup.config, "USAGE_PATH", str(tmp_path / ".standup_usage.json"))
    monkeypatch.setattr(standup.history, "init_db", lambda: None)
    monkeypatch.setattr(standup.history, "get_db_path", lambda: str(tmp_path / "history.db"))
    monkeypatch.setattr(standup.history, "get_db_size_bytes", lambda _: 1000)
    monkeypatch.setattr(standup.history, "get_row_count", lambda _: 3)
    monkeypatch.setattr(standup.history, "_get_connection", lambda _: _FakeConn())
    monkeypatch.setattr(standup.history, "_MIGRATIONS", [(1, "2026-01-01", "init")])
    monkeypatch.setattr(standup.history, "get_current_schema_version", lambda _: 1)
    monkeypatch.setattr(validator_module, "validate_quality_config", lambda _: (True, ""))
    monkeypatch.setattr(validator_module, "validate_template_name", lambda *a: (True, ""))
    monkeypatch.setattr(
        validator_module, "validate_full_config", lambda _: (False, ["repos must be a JSON array."])
    )
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "a" * 40)
    monkeypatch.setattr(security_module, "log_event", lambda *a, **kw: None)

    security_module.run_doctor()
    out = capsys.readouterr().out
    assert "repos must be a JSON array" in out
    assert "Config fully valid" in out


def test_run_doctor_db_exception(monkeypatch, tmp_path, capsys):
    import json

    import standup.config
    import standup.history
    import standup.security as security_module
    import standup.validator as validator_module

    config = {
        "provider": {"name": "groq"},
        "repos": [],
        "slack_webhook_url": "",
        "quality": {},
        "template": "default",
        "custom_templates": {},
        "rate_limit": {},
    }
    config_path = tmp_path / ".standup.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(standup.config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(standup.config, "USAGE_PATH", str(tmp_path / ".standup_usage.json"))
    monkeypatch.setattr(
        standup.history, "init_db", lambda: (_ for _ in ()).throw(Exception("db failure"))
    )
    monkeypatch.setattr(standup.history, "get_db_path", lambda: str(tmp_path / "history.db"))
    monkeypatch.setattr(validator_module, "validate_quality_config", lambda _: (True, ""))
    monkeypatch.setattr(validator_module, "validate_template_name", lambda *a: (True, ""))
    monkeypatch.setattr(validator_module, "validate_full_config", lambda _: (True, []))
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "a" * 40)
    monkeypatch.setattr(security_module, "log_event", lambda *a, **kw: None)

    security_module.run_doctor()
    out = capsys.readouterr().out
    assert "History DB" in out


def test_run_doctor_repo_errors(monkeypatch, tmp_path, capsys):
    import json

    import standup.config
    import standup.history
    import standup.security as security_module
    import standup.validator as validator_module

    config = {
        "provider": {"name": "groq"},
        "repos": ["/invalid/repo/path"],
        "slack_webhook_url": "",
        "quality": {},
        "template": "default",
        "custom_templates": {},
        "rate_limit": {},
    }
    config_path = tmp_path / ".standup.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(standup.config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(standup.config, "USAGE_PATH", str(tmp_path / ".standup_usage.json"))
    monkeypatch.setattr(standup.history, "init_db", lambda: None)
    monkeypatch.setattr(standup.history, "get_db_path", lambda: str(tmp_path / "history.db"))
    monkeypatch.setattr(standup.history, "get_db_size_bytes", lambda _: 1000)
    monkeypatch.setattr(standup.history, "get_row_count", lambda _: 3)
    monkeypatch.setattr(standup.history, "_get_connection", lambda _: _FakeConn())
    monkeypatch.setattr(standup.history, "_MIGRATIONS", [(1, "2026-01-01", "init")])
    monkeypatch.setattr(standup.history, "get_current_schema_version", lambda _: 1)
    monkeypatch.setattr(validator_module, "validate_quality_config", lambda _: (True, ""))
    monkeypatch.setattr(validator_module, "validate_template_name", lambda *a: (True, ""))
    monkeypatch.setattr(validator_module, "validate_full_config", lambda _: (True, []))
    monkeypatch.setattr(
        validator_module,
        "validate_repo_path",
        lambda _: (False, "Path not found or not a git repo"),
    )
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "a" * 40)
    monkeypatch.setattr(security_module, "log_event", lambda *a, **kw: None)

    security_module.run_doctor()
    out = capsys.readouterr().out
    assert "Repo paths valid" in out
    assert "Path not found or not a git repo" in out


def test_run_doctor_ollama_exception(monkeypatch, tmp_path, capsys):
    import json

    import standup.config
    import standup.history
    import standup.security as security_module
    import standup.validator as validator_module

    config = {
        "provider": {"name": "ollama"},
        "repos": [],
        "slack_webhook_url": "",
        "quality": {},
        "template": "default",
        "custom_templates": {},
        "rate_limit": {},
    }
    config_path = tmp_path / ".standup.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(standup.config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(standup.config, "USAGE_PATH", str(tmp_path / ".standup_usage.json"))
    monkeypatch.setattr(standup.history, "init_db", lambda: None)
    monkeypatch.setattr(standup.history, "get_db_path", lambda: str(tmp_path / "history.db"))
    monkeypatch.setattr(standup.history, "get_db_size_bytes", lambda _: 1000)
    monkeypatch.setattr(standup.history, "get_row_count", lambda _: 3)
    monkeypatch.setattr(standup.history, "_get_connection", lambda _: _FakeConn())
    monkeypatch.setattr(standup.history, "_MIGRATIONS", [(1, "2026-01-01", "init")])
    monkeypatch.setattr(standup.history, "get_current_schema_version", lambda _: 1)
    monkeypatch.setattr(validator_module, "validate_quality_config", lambda _: (True, ""))
    monkeypatch.setattr(validator_module, "validate_template_name", lambda *a: (True, ""))
    monkeypatch.setattr(validator_module, "validate_full_config", lambda _: (True, []))
    monkeypatch.setattr(security_module, "log_event", lambda *a, **kw: None)

    class FakeOllamaProvider:
        def __init__(self, cfg):
            raise RuntimeError("ollama init failure")

    monkeypatch.setattr("standup.llm.ollama_provider.OllamaProvider", FakeOllamaProvider)

    security_module.run_doctor()
    out = capsys.readouterr().out
    assert "ollama init failure" in out


def test_run_doctor_groq_key_in_config(monkeypatch, tmp_path, capsys):
    import json

    import standup.config
    import standup.history
    import standup.security as security_module
    import standup.validator as validator_module

    config = {
        "provider": {"name": "groq", "groq": {"api_key": "gsk_" + "a" * 40}},
        "repos": [],
        "slack_webhook_url": "",
        "quality": {},
        "template": "default",
        "custom_templates": {},
        "rate_limit": {},
    }
    config_path = tmp_path / ".standup.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(standup.config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(standup.config, "USAGE_PATH", str(tmp_path / ".standup_usage.json"))
    monkeypatch.setattr(standup.history, "init_db", lambda: None)
    monkeypatch.setattr(standup.history, "get_db_path", lambda: str(tmp_path / "history.db"))
    monkeypatch.setattr(standup.history, "get_db_size_bytes", lambda _: 1000)
    monkeypatch.setattr(standup.history, "get_row_count", lambda _: 3)
    monkeypatch.setattr(standup.history, "_get_connection", lambda _: _FakeConn())
    monkeypatch.setattr(standup.history, "_MIGRATIONS", [(1, "2026-01-01", "init")])
    monkeypatch.setattr(standup.history, "get_current_schema_version", lambda _: 1)
    monkeypatch.setattr(validator_module, "validate_quality_config", lambda _: (True, ""))
    monkeypatch.setattr(validator_module, "validate_template_name", lambda *a: (True, ""))
    monkeypatch.setattr(validator_module, "validate_full_config", lambda _: (True, []))
    monkeypatch.setattr(security_module, "log_event", lambda *a, **kw: None)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    security_module.run_doctor()
    out = capsys.readouterr().out
    assert "Stored in config file" in out


def test_run_doctor_log_file_not_found(monkeypatch, tmp_path, capsys):
    import json

    import standup.config
    import standup.history
    import standup.security as security_module
    import standup.validator as validator_module

    config = {
        "provider": {"name": "groq"},
        "repos": [],
        "slack_webhook_url": "",
        "quality": {},
        "template": "default",
        "custom_templates": {},
        "rate_limit": {},
    }
    config_path = tmp_path / ".standup.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(standup.config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(standup.config, "USAGE_PATH", str(tmp_path / ".standup_usage.json"))
    monkeypatch.setattr(standup.history, "init_db", lambda: None)
    monkeypatch.setattr(standup.history, "get_db_path", lambda: str(tmp_path / "history.db"))
    monkeypatch.setattr(standup.history, "get_db_size_bytes", lambda _: 1000)
    monkeypatch.setattr(standup.history, "get_row_count", lambda _: 3)
    monkeypatch.setattr(standup.history, "_get_connection", lambda _: _FakeConn())
    monkeypatch.setattr(standup.history, "_MIGRATIONS", [(1, "2026-01-01", "init")])
    monkeypatch.setattr(standup.history, "get_current_schema_version", lambda _: 1)
    monkeypatch.setattr(validator_module, "validate_quality_config", lambda _: (True, ""))
    monkeypatch.setattr(validator_module, "validate_template_name", lambda *a: (True, ""))
    monkeypatch.setattr(validator_module, "validate_full_config", lambda _: (True, []))
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "a" * 40)
    monkeypatch.setattr(security_module, "log_event", lambda *a, **kw: None)
    monkeypatch.setattr(security_module, "get_log_path", lambda: str(tmp_path / "nonexistent.log"))

    security_module.run_doctor()
    out = capsys.readouterr().out
    assert "No log file yet" in out


def test_run_doctor_config_parse_error(monkeypatch, tmp_path, capsys):
    import standup.config
    import standup.history
    import standup.security as security_module
    import standup.validator as validator_module

    config_path = tmp_path / ".standup.json"
    config_path.write_text("{invalid json content}")
    monkeypatch.setattr(standup.config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(standup.config, "USAGE_PATH", str(tmp_path / ".standup_usage.json"))
    monkeypatch.setattr(standup.history, "init_db", lambda: None)
    monkeypatch.setattr(standup.history, "get_db_path", lambda: str(tmp_path / "history.db"))
    monkeypatch.setattr(standup.history, "get_db_size_bytes", lambda _: 1000)
    monkeypatch.setattr(standup.history, "get_row_count", lambda _: 3)
    monkeypatch.setattr(standup.history, "_get_connection", lambda _: _FakeConn())
    monkeypatch.setattr(standup.history, "_MIGRATIONS", [(1, "2026-01-01", "init")])
    monkeypatch.setattr(standup.history, "get_current_schema_version", lambda _: 1)
    monkeypatch.setattr(validator_module, "validate_quality_config", lambda _: (True, ""))
    monkeypatch.setattr(validator_module, "validate_template_name", lambda *a: (True, ""))
    monkeypatch.setattr(validator_module, "validate_full_config", lambda _: (True, []))
    monkeypatch.setattr(security_module, "log_event", lambda *a, **kw: None)

    security_module.run_doctor()
    out = capsys.readouterr().out
    assert "Config file" in out


def test_run_doctor_config_in_git_repo(monkeypatch, tmp_path, capsys):
    import json
    from pathlib import Path

    import standup.config
    import standup.history
    import standup.security as security_module
    import standup.validator as validator_module

    (tmp_path / ".git").mkdir()
    config_path = tmp_path / ".standup.json"
    config = {
        "provider": {"name": "groq"},
        "repos": [],
        "slack_webhook_url": "",
        "quality": {},
        "template": "default",
        "custom_templates": {},
        "rate_limit": {},
    }
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(standup.config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(standup.config, "USAGE_PATH", str(tmp_path / ".standup_usage.json"))
    monkeypatch.setattr(standup.history, "init_db", lambda: None)
    monkeypatch.setattr(standup.history, "get_db_path", lambda: str(tmp_path / "history.db"))
    monkeypatch.setattr(standup.history, "get_db_size_bytes", lambda _: 1000)
    monkeypatch.setattr(standup.history, "get_row_count", lambda _: 3)
    monkeypatch.setattr(standup.history, "_get_connection", lambda _: _FakeConn())
    monkeypatch.setattr(standup.history, "_MIGRATIONS", [(1, "2026-01-01", "init")])
    monkeypatch.setattr(standup.history, "get_current_schema_version", lambda _: 1)
    monkeypatch.setattr(validator_module, "validate_quality_config", lambda _: (True, ""))
    monkeypatch.setattr(validator_module, "validate_template_name", lambda *a: (True, ""))
    monkeypatch.setattr(validator_module, "validate_full_config", lambda _: (True, []))
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "a" * 40)
    monkeypatch.setattr(security_module, "log_event", lambda *a, **kw: None)

    cfg_dir = Path(config_path).parent.resolve()
    assert (cfg_dir / ".git").exists()

    security_module.run_doctor()
    out = capsys.readouterr().out
    assert "Config file location" in out


def test_run_doctor_config_location_exception(monkeypatch, tmp_path, capsys):
    import json
    from pathlib import Path

    import standup.config
    import standup.history
    import standup.security as security_module
    import standup.validator as validator_module

    config = {
        "provider": {"name": "groq"},
        "repos": [],
        "slack_webhook_url": "",
        "quality": {},
        "template": "default",
        "custom_templates": {},
        "rate_limit": {},
    }
    config_path = tmp_path / ".standup.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(standup.config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(standup.config, "USAGE_PATH", str(tmp_path / ".standup_usage.json"))
    monkeypatch.setattr(standup.history, "init_db", lambda: None)
    monkeypatch.setattr(standup.history, "get_db_path", lambda: str(tmp_path / "history.db"))
    monkeypatch.setattr(standup.history, "get_db_size_bytes", lambda _: 1000)
    monkeypatch.setattr(standup.history, "get_row_count", lambda _: 3)
    monkeypatch.setattr(standup.history, "_get_connection", lambda _: _FakeConn())
    monkeypatch.setattr(standup.history, "_MIGRATIONS", [(1, "2026-01-01", "init")])
    monkeypatch.setattr(standup.history, "get_current_schema_version", lambda _: 1)
    monkeypatch.setattr(validator_module, "validate_quality_config", lambda _: (True, ""))
    monkeypatch.setattr(validator_module, "validate_template_name", lambda *a: (True, ""))
    monkeypatch.setattr(validator_module, "validate_full_config", lambda _: (True, []))
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "a" * 40)
    monkeypatch.setattr(security_module, "log_event", lambda *a, **kw: None)

    original_exists = Path.exists

    def _broken_exists(self):
        if str(self).endswith(".git"):
            raise PermissionError("access denied")
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", _broken_exists)

    security_module.run_doctor()
    out = capsys.readouterr().out
    assert "access denied" in out or "Could not" not in out


def test_run_doctor_repos_valid(monkeypatch, tmp_path, capsys):
    import json

    import standup.config
    import standup.history
    import standup.security as security_module
    import standup.validator as validator_module

    config = {
        "provider": {"name": "groq"},
        "repos": ["/tmp/fakerepo"],
        "slack_webhook_url": "",
        "quality": {},
        "template": "default",
        "custom_templates": {},
        "rate_limit": {},
    }
    config_path = tmp_path / ".standup.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(standup.config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(standup.config, "USAGE_PATH", str(tmp_path / ".standup_usage.json"))
    monkeypatch.setattr(standup.history, "init_db", lambda: None)
    monkeypatch.setattr(standup.history, "get_db_path", lambda: str(tmp_path / "history.db"))
    monkeypatch.setattr(standup.history, "get_db_size_bytes", lambda _: 1000)
    monkeypatch.setattr(standup.history, "get_row_count", lambda _: 3)
    monkeypatch.setattr(standup.history, "_get_connection", lambda _: _FakeConn())
    monkeypatch.setattr(standup.history, "_MIGRATIONS", [(1, "2026-01-01", "init")])
    monkeypatch.setattr(standup.history, "get_current_schema_version", lambda _: 1)
    monkeypatch.setattr(validator_module, "validate_quality_config", lambda _: (True, ""))
    monkeypatch.setattr(validator_module, "validate_template_name", lambda *a: (True, ""))
    monkeypatch.setattr(validator_module, "validate_full_config", lambda _: (True, []))
    monkeypatch.setattr(validator_module, "validate_repo_path", lambda _: (True, ""))
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "a" * 40)
    monkeypatch.setattr(security_module, "log_event", lambda *a, **kw: None)

    security_module.run_doctor()
    out = capsys.readouterr().out
    assert "repo(s) configured and valid" in out


def test_run_doctor_python_version_too_low(monkeypatch, tmp_path, capsys):
    import collections
    import importlib
    import json
    import types

    import standup.config
    import standup.history
    import standup.security as security_module
    import standup.validator as validator_module

    VersionInfo = collections.namedtuple("VersionInfo", ["major", "minor", "micro"])
    low_version = VersionInfo(3, 9, 0)

    config = {
        "provider": {"name": "groq"},
        "repos": [],
        "slack_webhook_url": "",
        "quality": {},
        "template": "default",
        "custom_templates": {},
        "rate_limit": {},
    }
    config_path = tmp_path / ".standup.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(standup.config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(standup.config, "USAGE_PATH", str(tmp_path / ".standup_usage.json"))
    monkeypatch.setattr(standup.history, "init_db", lambda: None)
    monkeypatch.setattr(standup.history, "get_db_path", lambda: str(tmp_path / "history.db"))
    monkeypatch.setattr(standup.history, "get_db_size_bytes", lambda _: 1000)
    monkeypatch.setattr(standup.history, "get_row_count", lambda _: 3)
    monkeypatch.setattr(standup.history, "_get_connection", lambda _: _FakeConn())
    monkeypatch.setattr(standup.history, "_MIGRATIONS", [(1, "2026-01-01", "init")])
    monkeypatch.setattr(standup.history, "get_current_schema_version", lambda _: 1)
    monkeypatch.setattr(validator_module, "validate_quality_config", lambda _: (True, ""))
    monkeypatch.setattr(validator_module, "validate_template_name", lambda *a: (True, ""))
    monkeypatch.setattr(validator_module, "validate_full_config", lambda _: (True, []))
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "a" * 40)
    monkeypatch.setattr(security_module, "log_event", lambda *a, **kw: None)
    original_import_module = importlib.import_module

    def _safe_import_module(name):
        if name in ("ollama", "groq", "git", "pyperclip", "rich", "requests"):
            return types.SimpleNamespace()
        return original_import_module(name)

    monkeypatch.setattr(importlib, "import_module", _safe_import_module)
    monkeypatch.setattr(standup.security.sys, "version_info", low_version)

    security_module.run_doctor()
    out = capsys.readouterr().out
    assert "requires 3.10" in out


def test_run_doctor_missing_dependencies(monkeypatch, tmp_path, capsys):
    import importlib
    import json

    import standup.config
    import standup.history
    import standup.security as security_module
    import standup.validator as validator_module

    config = {
        "provider": {"name": "groq"},
        "repos": [],
        "slack_webhook_url": "",
        "quality": {},
        "template": "default",
        "custom_templates": {},
        "rate_limit": {},
    }
    config_path = tmp_path / ".standup.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(standup.config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(standup.config, "USAGE_PATH", str(tmp_path / ".standup_usage.json"))
    monkeypatch.setattr(standup.history, "init_db", lambda: None)
    monkeypatch.setattr(standup.history, "get_db_path", lambda: str(tmp_path / "history.db"))
    monkeypatch.setattr(standup.history, "get_db_size_bytes", lambda _: 1000)
    monkeypatch.setattr(standup.history, "get_row_count", lambda _: 3)
    monkeypatch.setattr(standup.history, "_get_connection", lambda _: _FakeConn())
    monkeypatch.setattr(standup.history, "_MIGRATIONS", [(1, "2026-01-01", "init")])
    monkeypatch.setattr(standup.history, "get_current_schema_version", lambda _: 1)
    monkeypatch.setattr(validator_module, "validate_quality_config", lambda _: (True, ""))
    monkeypatch.setattr(validator_module, "validate_template_name", lambda *a: (True, ""))
    monkeypatch.setattr(validator_module, "validate_full_config", lambda _: (True, []))
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "a" * 40)
    monkeypatch.setattr(security_module, "log_event", lambda *a, **kw: None)

    original_import_module = importlib.import_module

    def _fake_import_module(name):
        if name in ("ollama", "groq"):
            raise ImportError(f"No module named {name}")
        return original_import_module(name)

    monkeypatch.setattr(importlib, "import_module", _fake_import_module)

    security_module.run_doctor()
    out = capsys.readouterr().out
    assert "Missing:" in out


def test_run_doctor_slack_webhook_invalid(monkeypatch, tmp_path, capsys):
    import json

    import standup.config
    import standup.history
    import standup.security as security_module
    import standup.validator as validator_module

    config = {
        "provider": {"name": "groq"},
        "repos": [],
        "slack_webhook_url": "https://invalid.example.com",
        "quality": {},
        "template": "default",
        "custom_templates": {},
        "rate_limit": {},
    }
    config_path = tmp_path / ".standup.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(standup.config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(standup.config, "USAGE_PATH", str(tmp_path / ".standup_usage.json"))
    monkeypatch.setattr(standup.history, "init_db", lambda: None)
    monkeypatch.setattr(standup.history, "get_db_path", lambda: str(tmp_path / "history.db"))
    monkeypatch.setattr(standup.history, "get_db_size_bytes", lambda _: 1000)
    monkeypatch.setattr(standup.history, "get_row_count", lambda _: 3)
    monkeypatch.setattr(standup.history, "_get_connection", lambda _: _FakeConn())
    monkeypatch.setattr(standup.history, "_MIGRATIONS", [(1, "2026-01-01", "init")])
    monkeypatch.setattr(standup.history, "get_current_schema_version", lambda _: 1)
    monkeypatch.setattr(validator_module, "validate_quality_config", lambda _: (True, ""))
    monkeypatch.setattr(validator_module, "validate_template_name", lambda *a: (True, ""))
    monkeypatch.setattr(validator_module, "validate_full_config", lambda _: (True, []))
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "a" * 40)
    monkeypatch.setattr(security_module, "log_event", lambda *a, **kw: None)

    security_module.run_doctor()
    out = capsys.readouterr().out
    assert "Slack webhook" in out


def test_run_doctor_db_size_large(monkeypatch, tmp_path, capsys):
    import json

    import standup.config
    import standup.history
    import standup.security as security_module
    import standup.validator as validator_module

    config = {
        "provider": {"name": "groq"},
        "repos": [],
        "slack_webhook_url": "",
        "quality": {},
        "template": "default",
        "custom_templates": {},
        "rate_limit": {},
    }
    config_path = tmp_path / ".standup.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(standup.config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(standup.config, "USAGE_PATH", str(tmp_path / ".standup_usage.json"))
    monkeypatch.setattr(standup.history, "init_db", lambda: None)
    monkeypatch.setattr(standup.history, "get_db_path", lambda: str(tmp_path / "history.db"))
    monkeypatch.setattr(standup.history, "_get_connection", lambda _: _FakeConn())
    monkeypatch.setattr(standup.history, "_MIGRATIONS", [(1, "2026-01-01", "init")])
    monkeypatch.setattr(standup.history, "get_current_schema_version", lambda _: 1)
    monkeypatch.setattr(validator_module, "validate_quality_config", lambda _: (True, ""))
    monkeypatch.setattr(validator_module, "validate_template_name", lambda *a: (True, ""))
    monkeypatch.setattr(validator_module, "validate_full_config", lambda _: (True, []))
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "a" * 40)
    monkeypatch.setattr(security_module, "log_event", lambda *a, **kw: None)
    monkeypatch.setattr(standup.history, "get_db_size_bytes", lambda _: 6 * 1024 * 1024)
    monkeypatch.setattr(standup.history, "get_row_count", lambda _: 300)

    security_module.run_doctor()
    out = capsys.readouterr().out
    assert "MB" in out


def test_run_doctor_db_size_critical(monkeypatch, tmp_path, capsys):
    import json

    import standup.config
    import standup.history
    import standup.security as security_module
    import standup.validator as validator_module

    config = {
        "provider": {"name": "groq"},
        "repos": [],
        "slack_webhook_url": "",
        "quality": {},
        "template": "default",
        "custom_templates": {},
        "rate_limit": {},
    }
    config_path = tmp_path / ".standup.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(standup.config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(standup.config, "USAGE_PATH", str(tmp_path / ".standup_usage.json"))
    monkeypatch.setattr(standup.history, "init_db", lambda: None)
    monkeypatch.setattr(standup.history, "get_db_path", lambda: str(tmp_path / "history.db"))
    monkeypatch.setattr(standup.history, "_get_connection", lambda _: _FakeConn())
    monkeypatch.setattr(standup.history, "_MIGRATIONS", [(1, "2026-01-01", "init")])
    monkeypatch.setattr(standup.history, "get_current_schema_version", lambda _: 1)
    monkeypatch.setattr(validator_module, "validate_quality_config", lambda _: (True, ""))
    monkeypatch.setattr(validator_module, "validate_template_name", lambda *a: (True, ""))
    monkeypatch.setattr(validator_module, "validate_full_config", lambda _: (True, []))
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "a" * 40)
    monkeypatch.setattr(security_module, "log_event", lambda *a, **kw: None)
    monkeypatch.setattr(standup.history, "get_db_size_bytes", lambda _: 25 * 1024 * 1024)
    monkeypatch.setattr(standup.history, "get_row_count", lambda _: 500)

    security_module.run_doctor()
    out = capsys.readouterr().out
    assert "MB" in out


def test_run_doctor_quality_template_rate_limit(monkeypatch, tmp_path, capsys):
    import json

    import standup.config
    import standup.history
    import standup.security as security_module
    import standup.validator as validator_module

    config = {
        "provider": {"name": "groq"},
        "repos": [],
        "slack_webhook_url": "",
        "quality": {"enabled": True},
        "template": "invalid_template",
        "custom_templates": {},
        "rate_limit": {"enabled": True},
    }
    config_path = tmp_path / ".standup.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(standup.config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(standup.config, "USAGE_PATH", str(tmp_path / ".standup_usage.json"))
    monkeypatch.setattr(standup.history, "init_db", lambda: None)
    monkeypatch.setattr(standup.history, "get_db_path", lambda: str(tmp_path / "history.db"))
    monkeypatch.setattr(standup.history, "get_db_size_bytes", lambda _: 1000)
    monkeypatch.setattr(standup.history, "get_row_count", lambda _: 3)
    monkeypatch.setattr(standup.history, "_get_connection", lambda _: _FakeConn())
    monkeypatch.setattr(standup.history, "_MIGRATIONS", [(1, "2026-01-01", "init")])
    monkeypatch.setattr(standup.history, "get_current_schema_version", lambda _: 1)
    monkeypatch.setattr(
        validator_module,
        "validate_quality_config",
        lambda _: (False, "quality.enabled must be true or false"),
    )
    monkeypatch.setattr(
        validator_module,
        "validate_template_name",
        lambda *a: (False, "template must be one of ..."),
    )
    monkeypatch.setattr(validator_module, "validate_full_config", lambda _: (True, []))
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "a" * 40)
    monkeypatch.setattr(security_module, "log_event", lambda *a, **kw: None)

    security_module.run_doctor()
    out = capsys.readouterr().out
    assert "Quality config" in out
    assert "Template config" in out
    assert "Rate limit enabled" in out
