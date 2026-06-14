"""Tests for standup/git_reader.py."""

import subprocess
import sys
import types

import pytest

from standup.git_reader import _infer_modules, get_recent_commits
from standup.validator import MAX_COMMIT_MESSAGE_LENGTH, MAX_COMMITS_PER_RUN

# ---------------------------------------------------------------------------
# _infer_modules
# ---------------------------------------------------------------------------


def test_infer_modules_nested():
    files = ["src/auth/login.py", "src/models/user.py", "tests/unit/test_auth.py"]
    modules = _infer_modules(files)
    assert "auth" in modules
    assert "models" in modules
    assert "unit" in modules


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


def test_infer_modules_two_component_returns_directory_not_filename():
    """tests/test_auth.py should yield 'tests', not 'test_auth.py'."""
    modules = _infer_modules(["tests/test_auth.py"])
    assert modules == ["tests"]
    assert "test_auth.py" not in modules


def test_infer_modules_two_component_src():
    """src/app.py should yield 'src', not 'app.py'."""
    modules = _infer_modules(["src/app.py"])
    assert modules == ["src"]


def test_infer_modules_mixed_depths():
    """Two- and three-component paths in the same commit are handled correctly."""
    files = [
        "README.md",  # 1-level  → README.md
        "src/app.py",  # 2-level  → src
        "src/auth/login.py",  # 3-level  → auth
    ]
    modules = _infer_modules(files)
    assert "README.md" in modules
    assert "src" in modules
    assert "auth" in modules


# ---------------------------------------------------------------------------
# get_recent_commits (integration — requires git)
# ---------------------------------------------------------------------------


@pytest.fixture
def git_repo(tmp_path):
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
    file_path = tmp_path / "hello.py"
    file_path.write_text("print('hello')\n", encoding="utf-8")
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
    commit = commits[0]
    assert "repo" in commit
    assert "hash" in commit
    assert "message" in commit
    assert "timestamp" in commit
    assert "files_changed" in commit
    assert "insertions" in commit
    assert "deletions" in commit
    assert "modules" in commit


def test_get_recent_commits_message(git_repo):
    commits = get_recent_commits(str(git_repo), hours=24, author_email="")
    assert commits[0]["message"] == "initial commit"


def test_get_recent_commits_filter_by_email(git_repo):
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
    commits = get_recent_commits(str(git_repo), hours=0, author_email="")
    assert isinstance(commits, list)


def test_get_recent_commits_hash_length(git_repo):
    commits = get_recent_commits(str(git_repo), hours=24, author_email="")
    assert len(commits[0]["hash"]) == 7


def test_get_recent_commits_repo_name(git_repo):
    commits = get_recent_commits(str(git_repo), hours=24, author_email="")
    assert commits[0]["repo"] == git_repo.name


def test_get_recent_commits_truncates_message(monkeypatch):
    long_message = "x" * (MAX_COMMIT_MESSAGE_LENGTH + 50)

    class FakeCommit:
        hexsha = "abcdef1234567"
        message = long_message
        author = types.SimpleNamespace(email="dev@example.com")
        committed_datetime = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        )
        parents = []
        stats = types.SimpleNamespace(total={})

        def diff(self, *_args, **_kwargs):
            return []

    class FakeRepo:
        def iter_commits(self):
            return [FakeCommit()]

    fake_git = types.SimpleNamespace(
        Repo=lambda _path: FakeRepo(),
        NULL_TREE="NULL",
        exc=types.SimpleNamespace(
            InvalidGitRepositoryError=Exception,
            NoSuchPathError=Exception,
        ),
    )
    monkeypatch.setitem(sys.modules, "git", fake_git)
    commits = get_recent_commits("/tmp/repo", hours=24, author_email="")
    assert len(commits[0]["message"]) == MAX_COMMIT_MESSAGE_LENGTH


def test_get_recent_commits_caps_total_count(monkeypatch):
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)

    class FakeCommit:
        def __init__(self, index):
            self.hexsha = f"abcdef{index:06d}"
            self.message = f"commit {index}"
            self.author = types.SimpleNamespace(email="dev@example.com")
            self.committed_datetime = now
            self.parents = []
            self.stats = types.SimpleNamespace(total={})

        def diff(self, *_args, **_kwargs):
            return []

    class FakeRepo:
        def iter_commits(self):
            return [FakeCommit(index) for index in range(MAX_COMMITS_PER_RUN + 25)]

    fake_git = types.SimpleNamespace(
        Repo=lambda _path: FakeRepo(),
        NULL_TREE="NULL",
        exc=types.SimpleNamespace(
            InvalidGitRepositoryError=Exception,
            NoSuchPathError=Exception,
        ),
    )
    monkeypatch.setitem(sys.modules, "git", fake_git)
    commits = get_recent_commits("/tmp/repo", hours=24, author_email="")
    assert len(commits) == MAX_COMMITS_PER_RUN
