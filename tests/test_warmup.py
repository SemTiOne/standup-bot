"""Tests for standup/warmup.py."""

from standup.llm.groq_provider import GroqProvider
from standup.warmup import (
    _warm_up_generic,
    get_warm_up_script_content,
    is_model_warm,
    warm_up_ollama,
    warm_up_provider,
)


class DummyResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class DummyOllamaProvider:
    base_url = "http://localhost:11434"
    model = "llama3"

    def is_available(self):
        return True


class DummyProvider:
    def __init__(self, available):
        self._available = available

    def is_available(self):
        return self._available


def test_warm_up_ollama_success(monkeypatch):
    monkeypatch.setattr("standup.warmup.requests.post", lambda *args, **kwargs: DummyResponse(200))
    assert warm_up_ollama(DummyOllamaProvider(), verbose=True) is True


def test_warm_up_ollama_failure_status(monkeypatch):
    monkeypatch.setattr("standup.warmup.requests.post", lambda *args, **kwargs: DummyResponse(500))
    assert warm_up_ollama(DummyOllamaProvider(), verbose=False) is False


def test_warm_up_ollama_exception(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("network")

    monkeypatch.setattr("standup.warmup.requests.post", _boom)
    assert warm_up_ollama(DummyOllamaProvider(), verbose=True) is False


def test_is_model_warm_true_exact_name(monkeypatch):
    monkeypatch.setattr(
        "standup.warmup.requests.get",
        lambda *args, **kwargs: DummyResponse(200, {"models": [{"name": "llama3"}]}),
    )
    assert is_model_warm(DummyOllamaProvider()) is True


def test_is_model_warm_true_with_latest_suffix(monkeypatch):
    monkeypatch.setattr(
        "standup.warmup.requests.get",
        lambda *args, **kwargs: DummyResponse(200, {"models": [{"name": "llama3:latest"}]}),
    )
    assert is_model_warm(DummyOllamaProvider()) is True


def test_is_model_warm_false_on_missing_endpoint(monkeypatch):
    monkeypatch.setattr(
        "standup.warmup.requests.get", lambda *args, **kwargs: DummyResponse(404, {})
    )
    assert is_model_warm(DummyOllamaProvider()) is False


def test_is_model_warm_false_on_exception(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("fail")

    monkeypatch.setattr("standup.warmup.requests.get", _boom)
    assert is_model_warm(DummyOllamaProvider()) is False


def test_get_warm_up_script_content_windows(monkeypatch):
    monkeypatch.setattr("standup.warmup.sys.platform", "win32")
    script = get_warm_up_script_content({"name": "ollama"})
    assert "standup warm-up" in script
    assert "standup standup" not in script
    assert "Provider: ollama" in script


def test_get_warm_up_script_content_posix(monkeypatch):
    monkeypatch.setattr("standup.warmup.sys.platform", "linux")
    script = get_warm_up_script_content({"name": "groq"})
    assert script.startswith("#!/usr/bin/env bash")
    assert "standup warm-up" in script
    assert "standup standup" not in script


def test_warm_up_provider_groq_path(monkeypatch):
    provider = GroqProvider(
        {"provider": {"groq": {"api_key": "gsk_" + ("a" * 40), "model": "llama-3.1-8b-instant"}}}
    )
    monkeypatch.setattr(provider, "is_available", lambda: True)
    assert warm_up_provider(provider, verbose=True) is True


def test_warm_up_provider_generic_fallback(monkeypatch):
    assert warm_up_provider(DummyProvider(True), verbose=False) is True


def test_warm_up_provider_ollama_like_provider():
    assert warm_up_provider(DummyOllamaProvider(), verbose=False) is True


def test_warm_up_ollama_verbose_failure_status(monkeypatch):
    monkeypatch.setattr("standup.warmup.requests.post", lambda *args, **kwargs: DummyResponse(500))
    assert warm_up_ollama(DummyOllamaProvider(), verbose=True) is False


def test_warm_up_groq_not_available_verbose(monkeypatch):
    provider = GroqProvider(
        {"provider": {"groq": {"api_key": "gsk_" + ("a" * 40), "model": "llama-3.1-8b-instant"}}}
    )
    monkeypatch.setattr(provider, "is_available", lambda: False)
    assert warm_up_provider(provider, verbose=True) is False


def test_warm_up_groq_exception_verbose(monkeypatch):
    provider = GroqProvider(
        {"provider": {"groq": {"api_key": "gsk_" + ("a" * 40), "model": "llama-3.1-8b-instant"}}}
    )

    def _boom():
        raise RuntimeError("groq is down")

    monkeypatch.setattr(provider, "is_available", _boom)
    assert warm_up_provider(provider, verbose=True) is False


def test_warm_up_generic_verbose_success():
    assert warm_up_provider(DummyProvider(True), verbose=True) is True


def test_warm_up_generic_exception_verbose(monkeypatch):
    provider = DummyProvider(True)

    def _boom():
        raise RuntimeError("generic fail")

    monkeypatch.setattr(provider, "is_available", _boom)
    assert warm_up_provider(provider, verbose=True) is False


def test_warm_up_generic_direct_verbose_success(monkeypatch):
    assert _warm_up_generic(DummyProvider(True), verbose=True) is True


def test_warm_up_provider_real_ollama_instance(monkeypatch):
    from standup.llm.ollama_provider import OllamaProvider

    provider = object.__new__(OllamaProvider)
    provider.base_url = "http://localhost:11434"
    provider.model = "llama3"
    monkeypatch.setattr("standup.warmup.requests.post", lambda *args, **kwargs: DummyResponse(200))
    assert warm_up_provider(provider, verbose=False) is True
