"""Tests for standup/llm/base.py."""

from standup.llm.base import (
    DEFAULT_SYSTEM_PROMPT,
    BaseLLMProvider,
    LLMProviderError,
)


class _ConcreteProvider(BaseLLMProvider):
    def generate_standup(self, prompt: str, tone: str) -> str:
        return super().generate_standup(prompt, tone)

    def is_available(self) -> bool:
        return super().is_available()

    def get_provider_name(self) -> str:
        return super().get_provider_name()


def test_llm_provider_error_is_exception():
    assert issubclass(LLMProviderError, Exception)


def test_abstract_generate_standup_returns_none():
    provider = _ConcreteProvider()
    result = provider.generate_standup("test", "casual")
    assert result is None


def test_abstract_is_available_returns_none():
    provider = _ConcreteProvider()
    result = provider.is_available()
    assert result is None


def test_abstract_get_provider_name_returns_none():
    provider = _ConcreteProvider()
    result = provider.get_provider_name()
    assert result is None


def test_default_system_prompt_is_non_empty():
    assert isinstance(DEFAULT_SYSTEM_PROMPT, str)
    assert len(DEFAULT_SYSTEM_PROMPT) > 50
