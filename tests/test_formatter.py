"""Tests for standup/formatter.py."""

import pytest

from standup.formatter import build_standup_prompt, format_commits_for_prompt

_SAMPLE_COMMITS = [
    {
        "repo": "my-app",
        "hash": "abc1234",
        "message": "fix login bug",
        "timestamp": "2024-01-15 09:32",
        "files_changed": ["src/auth/login.py", "tests/test_auth.py"],
        "insertions": 42,
        "deletions": 7,
        "modules": ["auth", "tests"],
    },
    {
        "repo": "my-app",
        "hash": "def5678",
        "message": "refactor token validation",
        "timestamp": "2024-01-15 11:15",
        "files_changed": ["src/auth/tokens.py"],
        "insertions": 18,
        "deletions": 33,
        "modules": ["auth"],
    },
    {
        "repo": "api-service",
        "hash": "ghi9012",
        "message": "add /users endpoint",
        "timestamp": "2024-01-15 14:05",
        "files_changed": ["routes/users.py", "models/user.py"],
        "insertions": 91,
        "deletions": 2,
        "modules": ["routes", "models"],
    },
]


def test_format_commits_empty():
    result = format_commits_for_prompt([])
    assert result == ""


def test_format_commits_contains_repo_names():
    result = format_commits_for_prompt(_SAMPLE_COMMITS)
    assert "REPO: my-app" in result
    assert "REPO: api-service" in result


def test_format_commits_contains_messages():
    result = format_commits_for_prompt(_SAMPLE_COMMITS)
    assert "fix login bug" in result
    assert "add /users endpoint" in result


def test_format_commits_contains_stats():
    result = format_commits_for_prompt(_SAMPLE_COMMITS)
    assert "+42" in result or "42" in result
    assert "-7" in result or "7" in result


def test_format_commits_summary_line():
    result = format_commits_for_prompt(_SAMPLE_COMMITS)
    assert "SUMMARY:" in result
    assert "3 commit" in result


def test_format_commits_total_lines():
    result = format_commits_for_prompt(_SAMPLE_COMMITS)
    # Total insertions: 42 + 18 + 91 = 151
    assert "151" in result


def test_format_commits_single_repo():
    commits = [_SAMPLE_COMMITS[0]]
    result = format_commits_for_prompt(commits)
    assert "REPO: my-app" in result
    assert "REPO: api-service" not in result


def test_format_commits_files_truncated():
    """Files list should be truncated if more than 5 files."""
    commit = {
        "repo": "big-repo",
        "hash": "abc1234",
        "message": "huge change",
        "timestamp": "2024-01-15 10:00",
        "files_changed": [f"file{i}.py" for i in range(10)],
        "insertions": 100,
        "deletions": 50,
        "modules": ["src"],
    }
    result = format_commits_for_prompt([commit])
    assert "+5 more" in result


def test_build_standup_prompt_casual():
    prompt = build_standup_prompt("some commits", "casual")
    assert "casual" in prompt.lower() or "friendly" in prompt.lower()
    assert "**Yesterday:**" in prompt
    assert "**Today:**" in prompt
    assert "**Blockers:**" in prompt


def test_build_standup_prompt_formal():
    prompt = build_standup_prompt("some commits", "formal")
    assert "formal" in prompt.lower() or "professional" in prompt.lower()


def test_build_standup_prompt_includes_commits():
    prompt = build_standup_prompt("REPO: test\n- commit1", "casual")
    assert "REPO: test" in prompt


def test_format_commits_modules_in_summary():
    result = format_commits_for_prompt(_SAMPLE_COMMITS)
    # auth, tests, routes, models — at least one should appear
    assert any(m in result for m in ["auth", "tests", "routes", "models"])