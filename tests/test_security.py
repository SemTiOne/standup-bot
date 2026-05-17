"""Tests for standup/security.py."""

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
