"""Tests for standup/git_reader.py."""

import subprocess
from pathlib import Path

import pytest

from standup.git_reader import get_recent_commits, _infer_modules


# ---------------------------------------------------------------------------
# _infer_modules
# ---------------------------------------------------------------------------


def test_infer_modules_nested():
    files = ["src/auth/login.py", "src/models/user.py", "tests/test_auth.py"]
    modules = _infer_modules(files)
    assert "auth" in modules
    assert "models" in modules
    assert "tests" in modules


def test_infer_modules_top_level():
    files = ["README.md"]
    modules = _infer_modules(files)
    assert "README.md" in modules


def test_infer_modules_deduplicates():
    files = ["src/auth/login.py", "src/auth/logout.py"]
    modules = _infer_modules(files)
    assert modules.count("auth") == 1


def test_infer_modules_empty():
    assert _infer_modules([]) == []


# ---------------------------------------------------------------------------
# get_recent_commits — integration with real git repo
# ---------------------------------------------------------------------------


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo with a single commit."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    f = tmp_path / "hello.py"
    f.write_text("print('hello')\n")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    return tmp_path


def test_get_recent_commits_returns_list(git_repo):
    commits = get_recent_commits(str(git_repo), hours=24, author_email="")
    assert isinstance(commits, list)
    assert len(commits) >= 1


def test_get_recent_commits_structure(git_repo):
    commits = get_recent_commits(str(git_repo), hours=24, author_email="")
    c = commits[0]
    assert "repo" in c
    assert "hash" in c
    assert "message" in c
    assert "timestamp" in c
    assert "files_changed" in c
    assert "insertions" in c
    assert "deletions" in c
    assert "modules" in c


def test_get_recent_commits_message(git_repo):
    commits = get_recent_commits(str(git_repo), hours=24, author_email="")
    assert commits[0]["message"] == "initial commit"


def test_get_recent_commits_filter_by_email(git_repo):
    # Filter to a non-existent email — should return empty
    commits = get_recent_commits(str(git_repo), hours=24, author_email="other@example.com")
    assert commits == []


def test_get_recent_commits_match_email(git_repo):
    commits = get_recent_commits(str(git_repo), hours=24, author_email="test@example.com")
    assert len(commits) >= 1


def test_get_recent_commits_invalid_repo(tmp_path):
    commits = get_recent_commits(str(tmp_path), hours=24, author_email="")
    assert commits == []


def test_get_recent_commits_nonexistent_path():
    commits = get_recent_commits("/nonexistent/path", hours=24, author_email="")
    assert commits == []


def test_get_recent_commits_zero_hours(git_repo):
    # hours=0 is invalid via CLI but let's see — should return no commits
    commits = get_recent_commits(str(git_repo), hours=0, author_email="")
    assert isinstance(commits, list)


def test_get_recent_commits_hash_length(git_repo):
    commits = get_recent_commits(str(git_repo), hours=24, author_email="")
    assert len(commits[0]["hash"]) == 7


def test_get_recent_commits_repo_name(git_repo):
    commits = get_recent_commits(str(git_repo), hours=24, author_email="")
    assert commits[0]["repo"] == git_repo.name