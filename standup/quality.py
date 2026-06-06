"""
quality.py - Score standup output quality and retry weak summaries.

Quality scoring uses a fast secondary model call with a strict JSON response so
StandupBot can surface confidence and optionally improve low-scoring output.
"""

import json
import re
from typing import Dict, List

from standup.llm.base import BaseLLMProvider
from standup.llm.groq_provider import GroqProvider
from standup.llm.ollama_provider import OllamaProvider

SCORING_PROMPT_TEMPLATE = """You are a standup quality evaluator. Score the following standup summary on a scale of 0-100.

Criteria:
- Specificity (30pts): Does it mention actual work done, not vague generalities?
- Completeness (25pts): Does it cover Yesterday, Today, AND Blockers?
- Clarity (25pts): Is it readable, well-structured, and jargon-free?
- Actionability (20pts): Does "Today" describe concrete next steps?

Return ONLY a JSON object with this exact structure, no other text:
{{"score": <integer 0-100>, "issues": ["<issue1>", "<issue2>"], "strengths": ["<strength1>"]}}

Standup to evaluate:
{standup_text}
"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _fallback_score() -> Dict[str, object]:
    """
    Build the default score payload used on parsing or provider failure.

    Args:
        None.

    Returns:
        Score payload with zero score and empty lists.

    Raises:
        None.
    """
    return {"score": 0, "issues": [], "strengths": []}


def _extract_json(raw_text: str) -> Dict[str, object]:
    """
    Parse a score payload from raw model output.

    Args:
        raw_text: Provider response text that should contain JSON.

    Returns:
        Normalized score payload.

    Raises:
        None.
    """
    match = _JSON_RE.search(raw_text or "")
    if not match:
        return _fallback_score()

    try:
        payload = json.loads(match.group(0))
    except (TypeError, ValueError, json.JSONDecodeError):
        return _fallback_score()

    score = payload.get("score", 0)
    try:
        normalized_score = max(0, min(int(score), 100))
    except (TypeError, ValueError):
        normalized_score = 0

    issues = payload.get("issues", [])
    strengths = payload.get("strengths", [])
    if not isinstance(issues, list):
        issues = []
    if not isinstance(strengths, list):
        strengths = []

    return {
        "score": normalized_score,
        "issues": [str(item) for item in issues if str(item).strip()],
        "strengths": [str(item) for item in strengths if str(item).strip()],
    }


def _score_with_ollama(standup_text: str, provider: OllamaProvider) -> Dict[str, object]:
    """
    Run the quality evaluation prompt directly against Ollama.

    Args:
        standup_text: Standup output to score.
        provider: Configured Ollama provider instance.

    Returns:
        Parsed score payload or the fallback payload.

    Raises:
        None.
    """
    prompt = SCORING_PROMPT_TEMPLATE.format(standup_text=standup_text)
    try:
        import ollama  # type: ignore[import]

        client = ollama.Client(host=provider.base_url)
        response = client.chat(
            model=provider.model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0, "timeout": 30},
            format="json",
        )
        return _extract_json(response["message"]["content"])
    except Exception:
        return _fallback_score()


def _score_with_groq(standup_text: str, provider: GroqProvider) -> Dict[str, object]:
    """
    Run the quality evaluation prompt directly against Groq.

    Args:
        standup_text: Standup output to score.
        provider: Configured Groq provider instance.

    Returns:
        Parsed score payload or the fallback payload.

    Raises:
        None.
    """
    prompt = SCORING_PROMPT_TEMPLATE.format(standup_text=standup_text)
    if not provider.api_key:
        return _fallback_score()

    try:
        from groq import Groq  # type: ignore[import]

        client = Groq(api_key=provider.api_key, timeout=20.0)
        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=provider.model,
            temperature=0,
            response_format={"type": "json_object"},
        )
        return _extract_json(completion.choices[0].message.content or "")
    except Exception:
        return _fallback_score()


def score_standup(standup_text: str, provider: BaseLLMProvider) -> Dict[str, object]:
    """
    Score a generated standup on a 0-100 scale.

    Args:
        standup_text: Generated standup output to score.
        provider: Provider instance used to evaluate quality.

    Returns:
        Dict with ``score``, ``issues``, and ``strengths`` keys.

    Raises:
        None.
    """
    if isinstance(provider, OllamaProvider):
        return _score_with_ollama(standup_text, provider)
    if isinstance(provider, GroqProvider):
        return _score_with_groq(standup_text, provider)

    try:
        prompt = SCORING_PROMPT_TEMPLATE.format(standup_text=standup_text)
        response = provider.generate_standup(prompt, "formal")
        return _extract_json(response)
    except Exception:
        return _fallback_score()


def format_score_badge(score: int) -> str:
    """
    Format a color-coded badge for a numeric quality score.

    Args:
        score: Integer score between 0 and 100.

    Returns:
        Rich-formatted badge string.

    Raises:
        None.
    """
    if score >= 80:
        return "[black on green] HIGH [/black on green]"
    if score >= 60:
        return "[black on yellow] OK [/black on yellow]"
    return "[white on red] LOW [/white on red]"


def generate_with_quality_retry(
    prompt: str,
    provider: BaseLLMProvider,
    tone: str,
    min_score: int,
    max_retries: int = 2,
) -> Dict[str, object]:
    """
    Generate a standup and retry with guidance when quality is too low.

    Args:
        prompt: Base standup-generation prompt.
        provider: Provider used for generation and scoring.
        tone: Standup tone requested by the user.
        min_score: Minimum acceptable quality score.
        max_retries: Maximum number of refinement retries.

    Returns:
        Dict containing ``standup_text``, ``quality``, and ``retries``.

    Raises:
        None.
    """
    retries = 0
    current_prompt = prompt
    standup_text = provider.generate_standup(current_prompt, tone)
    quality = score_standup(standup_text, provider)

    while int(quality.get("score") or 0) < int(min_score) and retries < max_retries:  # type: ignore[call-overload]
        retries += 1
        issues = quality.get("issues", [])
        guidance_lines: List[str] = []
        if isinstance(issues, list) and issues:
            guidance_lines.extend(f"- {issue}" for issue in issues)
        else:
            guidance_lines.append(
                "- Improve specificity, completeness, clarity, and actionability."
            )

        joined_guidance = "\n".join(guidance_lines)
        current_prompt = (
            "Please revise the standup so it fixes these quality issues:\n"
            f"{joined_guidance}\n\nOriginal request:\n{prompt}"
        )
        standup_text = provider.generate_standup(current_prompt, tone)
        quality = score_standup(standup_text, provider)

    return {"standup_text": standup_text, "quality": quality, "retries": retries}
