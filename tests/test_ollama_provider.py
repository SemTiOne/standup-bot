"""Tests for standup/llm/ollama_provider.py."""

from unittest.mock import MagicMock, patch

import pytest

from standup.llm.base import LLMProviderError
from standup.llm.ollama_provider import _OLLAMA_REQUEST_TIMEOUT, OllamaProvider

_CONFIG = {
    "provider": {
        "ollama": {"base_url": "http://localhost:11434", "model": "llama3"},
    }
}


def _make_client_mock(content: str = "test standup") -> MagicMock:
    client = MagicMock()
    client.chat.return_value = {"message": {"content": content}}
    return client


# ---------------------------------------------------------------------------
# Regression: v0.2.3 timeout bug
# ---------------------------------------------------------------------------


def test_generate_standup_passes_timeout_to_client_not_options():
    """Regression test for v0.2.3: timeout must reach ollama.Client(), not
    the per-request `options` dict.

    The original bug passed `options={"timeout": 60}` to `client.chat()`.
    `options` is reserved for model parameters (temperature, top_p, etc.),
    so Ollama silently ignored the value and requests could hang forever.
    The fix moves the timeout to the `ollama.Client(..., timeout=...)`
    constructor, where it is honored by the underlying HTTP client.
    """
    mock_client = _make_client_mock()
    with patch("ollama.Client", return_value=mock_client) as mock_client_cls:
        provider = OllamaProvider(_CONFIG)
        provider.generate_standup("write a standup", "casual")

    # Client must be constructed with an explicit timeout kwarg.
    _, client_kwargs = mock_client_cls.call_args
    assert "timeout" in client_kwargs
    assert client_kwargs["timeout"] == _OLLAMA_REQUEST_TIMEOUT

    # `options`, if passed to chat() at all, must never carry "timeout",
    # that key belongs on the Client, not on a model-parameters dict.
    _, chat_kwargs = mock_client.chat.call_args
    options = chat_kwargs.get("options", {})
    assert "timeout" not in options


def test_generate_standup_returns_content_on_success():
    mock_client = _make_client_mock(content="- did a thing")
    with patch("ollama.Client", return_value=mock_client):
        provider = OllamaProvider(_CONFIG)
        result = provider.generate_standup("write a standup", "casual")
    assert result == "- did a thing"


def test_generate_standup_handles_null_content():
    """response['message']['content'] can be None on aborted generation."""
    mock_client = _make_client_mock()
    mock_client.chat.return_value = {"message": {"content": None}}
    with patch("ollama.Client", return_value=mock_client):
        provider = OllamaProvider(_CONFIG)
        result = provider.generate_standup("write a standup", "casual")
    assert result == ""


def test_generate_standup_connection_error_raises_friendly_message():
    mock_client = MagicMock()
    mock_client.chat.side_effect = ConnectionError("Connection refused")
    with patch("ollama.Client", return_value=mock_client):
        provider = OllamaProvider(_CONFIG)
        with pytest.raises(LLMProviderError, match="Ollama is not running"):
            provider.generate_standup("write a standup", "casual")


def test_generate_standup_model_not_found_raises_friendly_message():
    mock_client = MagicMock()
    mock_client.chat.side_effect = Exception("model 'llama3' not found")
    with patch("ollama.Client", return_value=mock_client):
        provider = OllamaProvider(_CONFIG)
        with pytest.raises(LLMProviderError, match="not available locally"):
            provider.generate_standup("write a standup", "casual")
