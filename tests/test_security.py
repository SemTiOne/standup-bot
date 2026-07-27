"""Tests for standup/security.py."""

import stat
import sys
from pathlib import Path

from standup.security import (
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


def test_store_secret_returns_false_without_a_keychain_backend():
    from standup.security import store_secret

    assert store_secret("groq_api_key", "gsk_test") is False


def test_get_secret_returns_none_without_a_keychain_backend():
    from standup.security import get_secret

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
    from standup.security import write_text_restricted

    target = tmp_path / "secret.json"
    write_text_restricted(str(target), '{"a": 1}', label="Test file")

    assert target.read_text(encoding="utf-8") == '{"a": 1}'
    if sys.platform != "win32":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600


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
        if sys.platform != "win32":
            assert stat.S_IMODE(Path(file_path).stat().st_mode) == 0o600
        assert Path(file_path).read_text(encoding="utf-8") == ""

    monkeypatch.setattr(security_module, "enforce_file_permissions", spy_enforce)

    real_write_text = Path.write_text

    def spy_write_text(self, data, *args, **kwargs):
        call_order.append("write")
        return real_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", spy_write_text)

    security_module.write_text_restricted(str(target), '{"secret": "value"}')

    assert call_order == ["enforce", "write"]


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
