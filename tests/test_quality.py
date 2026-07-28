"""Tests for standup/quality.py."""

from standup.quality import (
    _extract_json,
    _score_with_groq,
    _score_with_ollama,
    format_score_badge,
    generate_with_quality_retry,
    score_standup,
)


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)

    def generate_standup(self, prompt, tone):
        return self.responses.pop(0)


class ExplodingProvider:
    def generate_standup(self, prompt, tone):
        raise RuntimeError("boom")


def test_extract_json_parses_valid_payload():
    payload = _extract_json('{"score": 88, "issues": ["vague"], "strengths": ["clear"]}')
    assert payload["score"] == 88
    assert payload["issues"] == ["vague"]


def test_extract_json_handles_wrapped_text():
    payload = _extract_json('```json\n{"score": 75, "issues": [], "strengths": ["good"]}\n```')
    assert payload["score"] == 75


def test_extract_json_fallback_on_invalid_json():
    payload = _extract_json("not json")
    assert payload == {"score": 0, "issues": [], "strengths": []}


def test_format_score_badge_high():
    assert "green" in format_score_badge(90).lower()


def test_format_score_badge_medium():
    assert "yellow" in format_score_badge(70).lower()


def test_format_score_badge_low():
    assert "red" in format_score_badge(30).lower()


def test_score_standup_fallback_provider_success():
    provider = FakeProvider(['{"score": 81, "issues": ["minor"], "strengths": ["specific"]}'])
    result = score_standup("standup", provider)
    assert result["score"] == 81


def test_score_standup_fallback_provider_error_returns_zero():
    result = score_standup("standup", ExplodingProvider())
    assert result == {"score": 0, "issues": [], "strengths": []}


def test_generate_with_quality_retry_returns_first_good_result(monkeypatch):
    provider = FakeProvider(["draft one"])
    monkeypatch.setattr(
        "standup.quality.score_standup",
        lambda text, provider_obj: {"score": 90, "issues": [], "strengths": ["clear"]},
    )
    result = generate_with_quality_retry("prompt", provider, "casual", 80)
    assert result["standup_text"] == "draft one"
    assert result["retries"] == 0


def test_generate_with_quality_retry_retries_until_threshold(monkeypatch):
    provider = FakeProvider(["draft one", "draft two"])
    scores = [
        {"score": 40, "issues": ["too vague"], "strengths": []},
        {"score": 85, "issues": [], "strengths": ["specific"]},
    ]
    monkeypatch.setattr("standup.quality.score_standup", lambda text, provider_obj: scores.pop(0))
    result = generate_with_quality_retry("prompt", provider, "casual", 80)
    assert result["standup_text"] == "draft two"
    assert result["retries"] == 1
    assert result["quality"]["score"] == 85


def test_generate_with_quality_retry_stops_after_max_retries(monkeypatch):
    provider = FakeProvider(["one", "two", "three"])
    monkeypatch.setattr(
        "standup.quality.score_standup",
        lambda text, provider_obj: {"score": 10, "issues": ["bad"], "strengths": []},
    )
    result = generate_with_quality_retry("prompt", provider, "casual", 80)
    assert result["retries"] == 2
    assert result["standup_text"] == "three"


def test_extract_json_score_below_zero_clamps():
    payload = _extract_json('{"score": -10, "issues": [], "strengths": []}')
    assert payload["score"] == 0


def test_extract_json_score_above_100_clamps():
    payload = _extract_json('{"score": 150, "issues": [], "strengths": []}')
    assert payload["score"] == 100


def test_extract_json_score_none_returns_zero():
    payload = _extract_json('{"score": null, "issues": [], "strengths": []}')
    assert payload["score"] == 0


def test_extract_json_score_bad_string_returns_zero():
    payload = _extract_json('{"score": "bad", "issues": [], "strengths": []}')
    assert payload["score"] == 0


def test_extract_json_json_decode_error_after_match():
    payload = _extract_json("{invalid}")
    assert payload == {"score": 0, "issues": [], "strengths": []}


def test_extract_json_issues_not_a_list():
    payload = _extract_json('{"score": 80, "issues": "single issue", "strengths": []}')
    assert payload["issues"] == []


def test_extract_json_strengths_not_a_list():
    payload = _extract_json('{"score": 80, "issues": [], "strengths": {"key": "val"}}')
    assert payload["strengths"] == []


def test_score_with_ollama_success(monkeypatch):
    import sys
    import types

    ollama_mock = types.ModuleType("ollama")

    class MockClient:
        def __init__(self, **kwargs):
            pass

        def chat(self, **kwargs):
            return {"message": {"content": '{"score": 85, "issues": [], "strengths": ["clear"]}'}}

    ollama_mock.Client = MockClient
    monkeypatch.setitem(sys.modules, "ollama", ollama_mock)

    from standup.llm.ollama_provider import OllamaProvider

    provider = OllamaProvider({"provider": {"ollama": {}}})
    result = _score_with_ollama("test standup", provider)
    assert result["score"] == 85
    assert result["strengths"] == ["clear"]


def test_score_with_ollama_exception_returns_fallback(monkeypatch):
    import sys
    import types

    ollama_mock = types.ModuleType("ollama")

    class BrokenClient:
        def __init__(self, **kwargs):
            pass

        def chat(self, **kwargs):
            raise RuntimeError("ollama failed")

    ollama_mock.Client = BrokenClient
    monkeypatch.setitem(sys.modules, "ollama", ollama_mock)

    from standup.llm.ollama_provider import OllamaProvider

    provider = OllamaProvider({"provider": {"ollama": {}}})
    result = _score_with_ollama("test standup", provider)
    assert result == {"score": 0, "issues": [], "strengths": []}


def test_score_with_groq_no_api_key_returns_fallback(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    from standup.llm.groq_provider import GroqProvider

    provider = GroqProvider({"provider": {"groq": {}}})
    result = _score_with_groq("test standup", provider)
    assert result == {"score": 0, "issues": [], "strengths": []}


def test_score_with_groq_exception_returns_fallback(monkeypatch):
    import sys
    import types

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    groq_mock = types.ModuleType("groq")

    class BrokenGroq:
        def __init__(self, **kwargs):
            raise RuntimeError("groq unavailable")

    groq_mock.Groq = BrokenGroq
    monkeypatch.setitem(sys.modules, "groq", groq_mock)

    from standup.llm.groq_provider import GroqProvider

    provider = GroqProvider({"provider": {"groq": {"api_key": "test-key"}}})
    result = _score_with_groq("test standup", provider)
    assert result == {"score": 0, "issues": [], "strengths": []}


def test_score_standup_ollama_provider_path(monkeypatch):
    import sys
    import types

    ollama_mock = types.ModuleType("ollama")

    class MockClient:
        def __init__(self, **kwargs):
            pass

        def chat(self, **kwargs):
            return {"message": {"content": '{"score": 92, "issues": [], "strengths": ["great"]}'}}

    ollama_mock.Client = MockClient
    monkeypatch.setitem(sys.modules, "ollama", ollama_mock)

    from standup.llm.ollama_provider import OllamaProvider

    provider = OllamaProvider({"provider": {"ollama": {}}})
    result = score_standup("test standup", provider)
    assert result["score"] == 92


def test_score_standup_groq_provider_path(monkeypatch):
    import sys
    import types
    from unittest.mock import MagicMock

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    groq_mock = types.ModuleType("groq")
    mock_instance = MagicMock()
    mock_instance.chat.completions.create.return_value = MagicMock(
        choices=[
            MagicMock(
                message=MagicMock(content='{"score": 78, "issues": ["vague"], "strengths": []}')
            )
        ]
    )
    groq_mock.Groq = MagicMock(return_value=mock_instance)
    monkeypatch.setitem(sys.modules, "groq", groq_mock)

    from standup.llm.groq_provider import GroqProvider

    provider = GroqProvider({"provider": {"groq": {"api_key": "test-key"}}})
    result = score_standup("test standup", provider)
    assert result["score"] == 78


def test_generate_with_quality_retry_empty_issues_uses_fallback_guidance(monkeypatch):
    provider = FakeProvider(["draft one", "draft two"])
    scores = [
        {"score": 30, "issues": [], "strengths": []},
        {"score": 85, "issues": [], "strengths": ["better"]},
    ]
    monkeypatch.setattr("standup.quality.score_standup", lambda text, provider_obj: scores.pop(0))
    result = generate_with_quality_retry("prompt", provider, "casual", 80)
    assert result["standup_text"] == "draft two"
    assert result["retries"] == 1


def test_generate_with_quality_retry_non_list_issues_uses_fallback_guidance(monkeypatch):
    provider = FakeProvider(["draft one", "draft two"])
    scores = [
        {"score": 30, "issues": "not a list", "strengths": []},
        {"score": 85, "issues": [], "strengths": ["better"]},
    ]
    monkeypatch.setattr("standup.quality.score_standup", lambda text, provider_obj: scores.pop(0))
    result = generate_with_quality_retry("prompt", provider, "casual", 80)
    assert result["standup_text"] == "draft two"
    assert result["retries"] == 1
