"""
classifier.py - Classify commit messages and filter standup noise locally.

This module applies conventional-commit and heuristic pattern matching so
StandupBot can send higher-signal git activity to the LLM.
"""

import re

COMMIT_TYPES = {
    "feat": ("✨", "Feature"),
    "fix": ("🐛", "Bug Fix"),
    "refactor": ("", "Refactor"),
    "test": ("", "Tests"),
    "docs": ("", "Docs"),
    "chore": ("", "Chore"),
    "ci": ("", "CI/CD"),
    "perf": ("", "Performance"),
    "style": ("", "Style"),
    "revert": ("", "Revert"),
    "merge": ("", "Merge"),
    "wip": ("", "WIP"),
    "unknown": ("", "Other"),
}

NOISE_PATTERNS = [
    r"^merge (branch|pull request|remote)",
    r"^wip\b",
    r"^bump version",
    r"^\d+\.\d+\.\d+$",
    r"^update (changelog|readme)$",
    r"^initial commit$",
    r"^fixup!",
    r"^squash!",
]

_CONVENTIONAL_RE = re.compile(
    r"^(feat|fix|refactor|test|docs|chore|ci|perf|style|revert)"
    r"(?:\([^)]+\))?(?:!)?:",
    re.IGNORECASE,
)
_NOISE_REGEXES = [re.compile(pattern, re.IGNORECASE) for pattern in NOISE_PATTERNS]
_HEURISTICS = (
    ("merge", re.compile(r"^(merge|merged)\b", re.IGNORECASE)),
    ("wip", re.compile(r"^wip\b|work in progress", re.IGNORECASE)),
    ("revert", re.compile(r"^(revert|rollback)\b", re.IGNORECASE)),
    ("ci", re.compile(r"\b(ci|cd|workflow|github actions|pipeline)\b", re.IGNORECASE)),
    ("docs", re.compile(r"\b(doc|docs|readme|changelog|comment)\b", re.IGNORECASE)),
    ("test", re.compile(r"\b(test|tests|spec|pytest|unittest)\b", re.IGNORECASE)),
    ("refactor", re.compile(r"\b(refactor|cleanup|simplify|restructure)\b", re.IGNORECASE)),
    ("perf", re.compile(r"\b(perf|performance|optimi[sz]e|faster)\b", re.IGNORECASE)),
    ("style", re.compile(r"\b(style|format|lint|prettier|black|whitespace)\b", re.IGNORECASE)),
    ("fix", re.compile(r"\b(fix|bug|hotfix|patch|resolve)\b", re.IGNORECASE)),
    (
        "feat",
        re.compile(
            r"\b(add|adds|added|implement|implements|implemented|create|introduce|feature)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "chore",
        re.compile(
            r"\b(chore|deps|dependency|dependencies|bump|release|maintenance)\b", re.IGNORECASE
        ),
    ),
)


def classify_commit(message: str) -> str:
    """
    Classify a commit message into a standup-friendly commit type.

    Args:
        message: Commit subject line to classify.

    Returns:
        A key from ``COMMIT_TYPES``.

    Raises:
        None.
    """
    normalized = (message or "").strip()
    if not normalized:
        return "unknown"

    conventional_match = _CONVENTIONAL_RE.match(normalized)
    if conventional_match:
        return conventional_match.group(1).lower()

    for commit_type, pattern in _HEURISTICS:
        if pattern.search(normalized):
            return commit_type

    return "unknown"


def is_noise(message: str) -> bool:
    """
    Determine whether a commit message is likely standup noise.

    Args:
        message: Commit subject line to inspect.

    Returns:
        ``True`` when the commit should be filtered by default.

    Raises:
        None.
    """
    normalized = (message or "").strip()
    if not normalized:
        return True
    return any(pattern.search(normalized) for pattern in _NOISE_REGEXES)


def annotate_commits(commits: list[dict]) -> list[dict]:
    """
    Add commit type metadata without removing any commits.

    Args:
        commits: Commit dictionaries from ``git_reader``.

    Returns:
        A new list of commit dictionaries with ``type`` and ``type_emoji`` keys.

    Raises:
        None.
    """
    annotated: list[dict] = []
    for commit in commits:
        commit_type = classify_commit(commit.get("message", ""))
        emoji, _ = COMMIT_TYPES.get(commit_type, COMMIT_TYPES["unknown"])
        updated = dict(commit)
        updated["type"] = commit_type
        updated["type_emoji"] = emoji
        annotated.append(updated)
    return annotated


def filter_and_classify_commits(commits: list[dict]) -> list[dict]:
    """
    Remove low-signal commits and annotate the remainder with type metadata.

    Args:
        commits: Commit dictionaries from ``git_reader``.

    Returns:
        Filtered commit dictionaries with ``type`` and ``type_emoji`` keys.

    Raises:
        None.
    """
    filtered: list[dict] = []
    for commit in commits:
        if is_noise(commit.get("message", "")):
            continue
        filtered.extend(annotate_commits([commit]))
    return filtered


def summarize_by_type(commits: list[dict]) -> dict[str, int]:
    """
    Count commits by classified type.

    Args:
        commits: Commit dictionaries, optionally already annotated.

    Returns:
        Mapping of commit type key to occurrence count.

    Raises:
        None.
    """
    summary: dict[str, int] = {}
    for commit in commits:
        commit_type = commit.get("type") or classify_commit(commit.get("message", ""))
        summary[commit_type] = summary.get(commit_type, 0) + 1
    return summary
