"""Tests for standup/llm/ollama_provider.py."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from standup.llm.base import LLMProviderError
from standup.llm.ollama_provider import _OLLAMA_REQUEST_TIMEOUT, OllamaProvider
from standup.validator import MAX_LLM_RESPONSE_LENGTH

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


def test_generate_standup_ollama_not_installed():
    with patch("builtins.__import__") as mock_import:
        mock_import.side_effect = ImportError("No module named 'ollama'")
        provider = OllamaProvider(_CONFIG)
        with pytest.raises(LLMProviderError, match="pip install ollama"):
            provider.generate_standup("write a standup", "casual")


def test_generate_standup_formal_tone():
    mock_client = _make_client_mock(content="formal standup")
    with patch("ollama.Client", return_value=mock_client):
        provider = OllamaProvider(_CONFIG)
        result = provider.generate_standup("write a standup", "formal")
    assert result == "formal standup"


def test_generate_standup_truncates_long_response():
    long_content = "a" * (MAX_LLM_RESPONSE_LENGTH + 100)
    mock_client = _make_client_mock(content=long_content)
    with patch("ollama.Client", return_value=mock_client):
        provider = OllamaProvider(_CONFIG)
        result = provider.generate_standup("write a standup", "casual")
    assert len(result) == MAX_LLM_RESPONSE_LENGTH
    assert result == "a" * MAX_LLM_RESPONSE_LENGTH


def test_generate_standup_generic_error():
    mock_client = MagicMock()
    mock_client.chat.side_effect = Exception("something unexpected happened")
    with patch("ollama.Client", return_value=mock_client):
        provider = OllamaProvider(_CONFIG)
        with pytest.raises(LLMProviderError, match="Ollama could not generate a standup right now"):
            provider.generate_standup("write a standup", "casual")


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


def test_is_available_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"models": [{"name": "llama3"}, {"name": "llama3:latest"}]}
    with patch.object(requests, "get", return_value=mock_resp):
        provider = OllamaProvider(_CONFIG)
        assert provider.is_available() is True


def test_is_available_wrong_status():
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    with patch.object(requests, "get", return_value=mock_resp):
        provider = OllamaProvider(_CONFIG)
        assert provider.is_available() is False


def test_is_available_model_not_found():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"models": [{"name": "mistral"}, {"name": "codellama"}]}
    with patch.object(requests, "get", return_value=mock_resp):
        provider = OllamaProvider(_CONFIG)
        assert provider.is_available() is False


def test_is_available_connection_error():
    with patch.object(requests, "get", side_effect=ConnectionError("refused")):
        provider = OllamaProvider(_CONFIG)
        assert provider.is_available() is False


# ---------------------------------------------------------------------------
# get_provider_name
# ---------------------------------------------------------------------------


def test_get_provider_name():
    provider = OllamaProvider(_CONFIG)
    assert provider.get_provider_name() == "Ollama (llama3)"


def test_get_provider_name_default_model():
    provider = OllamaProvider({"provider": {"ollama": {}}})
    name = provider.get_provider_name()
    assert name.startswith("Ollama (")
    assert "llama" in name


# ---------------------------------------------------------------------------
# list_local_models
# ---------------------------------------------------------------------------


def test_list_local_models_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"models": [{"name": "llama3"}, {"name": "mistral"}]}
    with patch.object(requests, "get", return_value=mock_resp):
        provider = OllamaProvider(_CONFIG)
        result = provider.list_local_models()
    assert result == ["llama3", "mistral"]


def test_list_local_models_wrong_status():
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    with patch.object(requests, "get", return_value=mock_resp):
        provider = OllamaProvider(_CONFIG)
        assert provider.list_local_models() == []


def test_list_local_models_connection_error():
    with patch.object(requests, "get", side_effect=ConnectionError("refused")):
        provider = OllamaProvider(_CONFIG)
        assert provider.list_local_models() == []
