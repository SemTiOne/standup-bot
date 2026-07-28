"""Tests for standup/llm/groq_provider.py."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from standup.llm.base import LLMProviderError
from standup.llm.groq_provider import GROQ_SIGNUP_URL, GroqProvider
from standup.validator import MAX_LLM_RESPONSE_LENGTH

_CONFIG = {
    "provider": {
        "groq": {"api_key": "gsk_" + "a" * 40, "model": "llama-3.1-8b-instant"},
    }
}

_CONFIG_NO_KEY = {
    "provider": {
        "groq": {"api_key": "", "model": "llama-3.1-8b-instant"},
    }
}


def _make_mock_client(content: str = "test standup") -> MagicMock:
    mock_client = MagicMock()
    mock_completion = MagicMock()
    mock_completion.choices[0].message.content = content
    mock_client.chat.completions.create.return_value = mock_completion
    return mock_client


# ---------------------------------------------------------------------------
# generate_standup — missing API key
# ---------------------------------------------------------------------------


def test_generate_standup_no_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    provider = GroqProvider(_CONFIG_NO_KEY)
    with pytest.raises(LLMProviderError, match="Groq API key is invalid or missing"):
        provider.generate_standup("write a standup", "casual")


# ---------------------------------------------------------------------------
# generate_standup — groq package not installed
# ---------------------------------------------------------------------------


def test_generate_standup_groq_not_installed():
    fake_groq = MagicMock()
    del fake_groq.Groq
    with patch.dict("sys.modules", {"groq": fake_groq}):
        provider = GroqProvider(_CONFIG)
        with pytest.raises(LLMProviderError, match="pip install groq"):
            provider.generate_standup("write a standup", "casual")


# ---------------------------------------------------------------------------
# generate_standup — success
# ---------------------------------------------------------------------------


def test_generate_standup_returns_content_on_success():
    mock_client = _make_mock_client(content="- did a thing")
    with patch("groq.Groq", return_value=mock_client):
        provider = GroqProvider(_CONFIG)
        result = provider.generate_standup("write a standup", "casual")
    assert result == "- did a thing"


def test_generate_standup_formal_tone():
    mock_client = _make_mock_client(content="formal standup")
    with patch("groq.Groq", return_value=mock_client):
        provider = GroqProvider(_CONFIG)
        result = provider.generate_standup("write a standup", "formal")
    assert result == "formal standup"


def test_generate_standup_null_content():
    mock_client = _make_mock_client(content=None)
    with patch("groq.Groq", return_value=mock_client):
        provider = GroqProvider(_CONFIG)
        result = provider.generate_standup("write a standup", "casual")
    assert result == ""


def test_generate_standup_truncates_long_response():
    long_content = "a" * (MAX_LLM_RESPONSE_LENGTH + 100)
    mock_client = _make_mock_client(content=long_content)
    with patch("groq.Groq", return_value=mock_client):
        provider = GroqProvider(_CONFIG)
        result = provider.generate_standup("write a standup", "casual")
    assert len(result) == MAX_LLM_RESPONSE_LENGTH
    assert result == "a" * MAX_LLM_RESPONSE_LENGTH


# ---------------------------------------------------------------------------
# generate_standup — error handling
# ---------------------------------------------------------------------------


def test_generate_standup_401_error():
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("401 Unauthorized: invalid api key")
    with patch("groq.Groq", return_value=mock_client):
        provider = GroqProvider(_CONFIG)
        with pytest.raises(LLMProviderError, match="Groq API key is invalid or missing"):
            provider.generate_standup("write a standup", "casual")


def test_generate_standup_429_error():
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("429 Too Many Requests: rate limit")
    with patch("groq.Groq", return_value=mock_client):
        provider = GroqProvider(_CONFIG)
        with pytest.raises(LLMProviderError, match="Groq free tier rate limit hit"):
            provider.generate_standup("write a standup", "casual")


def test_generate_standup_generic_error():
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("server on fire")
    with patch("groq.Groq", return_value=mock_client):
        provider = GroqProvider(_CONFIG)
        with pytest.raises(LLMProviderError, match="Groq could not generate a standup right now"):
            provider.generate_standup("write a standup", "casual")


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


def test_is_available_no_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    provider = GroqProvider(_CONFIG_NO_KEY)
    assert provider.is_available() is False


def test_is_available_groq_not_installed():
    fake_groq = MagicMock()
    del fake_groq.Groq
    with patch.dict("sys.modules", {"groq": fake_groq}):
        provider = GroqProvider(_CONFIG)
        assert provider.is_available() is False


def test_is_available_api_error():
    mock_client = MagicMock()
    mock_client.models.list.side_effect = Exception("API error")
    with patch("groq.Groq", return_value=mock_client):
        provider = GroqProvider(_CONFIG)
        assert provider.is_available() is False


def test_is_available_success():
    mock_client = MagicMock()
    mock_client.models.list.return_value = None
    with patch("groq.Groq", return_value=mock_client):
        provider = GroqProvider(_CONFIG)
        assert provider.is_available() is True


# ---------------------------------------------------------------------------
# get_provider_name
# ---------------------------------------------------------------------------


def test_get_provider_name():
    provider = GroqProvider(_CONFIG)
    assert provider.get_provider_name() == "Groq (llama-3.1-8b-instant)"


def test_get_provider_name_default_model():
    provider = GroqProvider({"provider": {"groq": {}}})
    name = provider.get_provider_name()
    assert name.startswith("Groq (")
    assert "llama" in name
