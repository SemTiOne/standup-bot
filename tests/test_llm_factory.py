"""Tests for standup/llm/factory.py."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from standup.llm.base import LLMProviderError
from standup.llm.factory import get_provider, get_provider_with_fallback
from standup.llm.groq_provider import GroqProvider
from standup.llm.ollama_provider import OllamaProvider

_OLLAMA_CONFIG = {
    "provider": {
        "name": "ollama",
        "ollama": {"base_url": "http://localhost:11434", "model": "llama3"},
        "groq": {"api_key": "", "model": "llama3-8b-8192"},
    }
}

_GROQ_CONFIG = {
    "provider": {
        "name": "groq",
        "ollama": {"base_url": "http://localhost:11434", "model": "llama3"},
        "groq": {"api_key": "gsk_" + "a" * 40, "model": "llama3-8b-8192"},
    }
}


# ---------------------------------------------------------------------------
# get_provider
# ---------------------------------------------------------------------------


def test_get_provider_ollama():
    provider = get_provider(_OLLAMA_CONFIG)
    assert isinstance(provider, OllamaProvider)


def test_get_provider_groq():
    provider = get_provider(_GROQ_CONFIG)
    assert isinstance(provider, GroqProvider)


def test_get_provider_unknown():
    config = {"provider": {"name": "openai", "ollama": {}, "groq": {}}}
    with pytest.raises(ValueError, match="Unknown provider"):
        get_provider(config)


def test_get_provider_override_uses_override_not_config():
    # Config says ollama but override says groq
    provider = get_provider(_OLLAMA_CONFIG, override="groq")
    assert isinstance(provider, GroqProvider)


def test_get_provider_override_groq_to_ollama():
    # Config says groq but override says ollama
    provider = get_provider(_GROQ_CONFIG, override="ollama")
    assert isinstance(provider, OllamaProvider)


def test_get_provider_unknown_raises_with_valid_options():
    config = {"provider": {"name": "bad", "ollama": {}, "groq": {}}}
    with pytest.raises(ValueError) as exc_info:
        get_provider(config)
    assert "ollama" in str(exc_info.value).lower() or "groq" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# get_provider_with_fallback
# ---------------------------------------------------------------------------


def test_fallback_returns_ollama_when_available():
    with patch.object(OllamaProvider, "is_available", return_value=True):
        provider = get_provider_with_fallback(_OLLAMA_CONFIG)
        assert isinstance(provider, OllamaProvider)


def test_fallback_uses_groq_when_ollama_unavailable():
    with (
        patch.object(OllamaProvider, "is_available", return_value=False),
        patch.object(GroqProvider, "is_available", return_value=True),
    ):
        provider = get_provider_with_fallback(_OLLAMA_CONFIG)
        assert isinstance(provider, GroqProvider)


def test_fallback_exits_when_both_unavailable():
    with (
        patch.object(OllamaProvider, "is_available", return_value=False),
        patch.object(GroqProvider, "is_available", return_value=False),
        pytest.raises(SystemExit),
    ):
        get_provider_with_fallback(_OLLAMA_CONFIG)


def test_fallback_groq_configured_no_fallback():
    """When Groq is configured and unavailable, do not fall back — just exit."""
    with (
        patch.object(GroqProvider, "is_available", return_value=False),
        pytest.raises(SystemExit),
    ):
        get_provider_with_fallback(_GROQ_CONFIG)


def test_fallback_override_respected():
    """get_provider_with_fallback respects the override flag."""
    with patch.object(GroqProvider, "is_available", return_value=True):
        provider = get_provider_with_fallback(_OLLAMA_CONFIG, override="groq")
        assert isinstance(provider, GroqProvider)


def test_fallback_unknown_provider_exits():
    config = {"provider": {"name": "unknown", "ollama": {}, "groq": {}}}
    with pytest.raises(SystemExit):
        get_provider_with_fallback(config)


def test_fallback_ollama_unavailable_groq_also_unavailable_exits():
    with (
        patch.object(OllamaProvider, "is_available", return_value=False),
        patch.object(GroqProvider, "is_available", return_value=False),
        pytest.raises(SystemExit) as exc_info,
    ):
        get_provider_with_fallback(_OLLAMA_CONFIG)
    assert exc_info.value.code == 1