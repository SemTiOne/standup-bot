"""Tests for standup/security.py."""

import pytest

from standup.security import mask_api_key, redact_sensitive_patterns, validate_groq_api_key


# ---------------------------------------------------------------------------
# validate_groq_api_key
# ---------------------------------------------------------------------------


def test_valid_groq_key():
    key = "gsk_" + "a" * 40
    assert validate_groq_api_key(key) is True


def test_groq_key_wrong_prefix():
    key = "sk-" + "a" * 40
    assert validate_groq_api_key(key) is False


def test_groq_key_too_short():
    key = "gsk_abc"
    assert validate_groq_api_key(key) is False


def test_groq_key_not_string():
    assert validate_groq_api_key(None) is False  # type: ignore[arg-type]
    assert validate_groq_api_key(12345) is False  # type: ignore[arg-type]


def test_groq_key_exact_minimum():
    key = "gsk_" + "a" * 36  # total 40 chars
    assert validate_groq_api_key(key) is True


# ---------------------------------------------------------------------------
# mask_api_key
# ---------------------------------------------------------------------------


def test_mask_api_key_format():
    key = "gsk_abcdefghij" + "x" * 30 + "ZZZZ"
    masked = mask_api_key(key)
    assert masked.startswith("gsk_abcdef")
    assert masked.endswith("ZZZZ")
    assert "****" in masked


def test_mask_api_key_short():
    assert mask_api_key("short") == "****"


def test_mask_api_key_none():
    assert mask_api_key(None) == "****"  # type: ignore[arg-type]


def test_mask_api_key_hides_middle():
    key = "gsk_" + "A" * 40 + "ZZZZ"
    masked = mask_api_key(key)
    # Should not contain a long run of 'A's
    assert "AAAAAAAAAA" not in masked


# ---------------------------------------------------------------------------
# redact_sensitive_patterns
# ---------------------------------------------------------------------------


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


def test_redact_api_key_pattern():
    text = "api_key=abc123xyz in request"
    result = redact_sensitive_patterns(text)
    assert "abc123xyz" not in result