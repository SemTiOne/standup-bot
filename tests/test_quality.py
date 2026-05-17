"""Tests for standup/quality.py."""

from standup.quality import _extract_json, format_score_badge, generate_with_quality_retry, score_standup


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
    monkeypatch.setattr("standup.quality.score_standup", lambda text, provider_obj: {"score": 90, "issues": [], "strengths": ["clear"]})
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
    monkeypatch.setattr("standup.quality.score_standup", lambda text, provider_obj: {"score": 10, "issues": ["bad"], "strengths": []})
    result = generate_with_quality_retry("prompt", provider, "casual", 80)
    assert result["retries"] == 2
    assert result["standup_text"] == "three"
