"""
git_reader.py - Git log parsing logic.

Reads recent commits from one or more local git repositories while applying
defensive caps to untrusted git metadata.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from rich.console import Console

from standup.logger import log_event
from standup.security import sanitize_error_message
from standup.validator import MAX_COMMIT_MESSAGE_LENGTH, MAX_COMMITS_PER_RUN

console = Console()


def _infer_modules(files: list[str]) -> list[str]:
    """
    Infer top-level module names from a list of file paths.

    For paths with three or more components (``src/auth/login.py``) the second
    component is returned — the immediate sub-package rather than the generic
    top-level directory.  For two-component paths (``tests/test_auth.py``) the
    first component is returned so the result is a directory name rather than
    a bare filename.  Single-component paths (root-level files) return the
    filename itself.

    Args:
        files: Changed file paths from a commit.

    Returns:
        Sorted unique module names.

    Raises:
        None.
    """
    modules = set()
    for file_path in files:
        parts = Path(file_path).parts
        if len(parts) >= 3:
            modules.add(parts[1])
        elif len(parts) in (1, 2):
            modules.add(parts[0])
    return sorted(modules)


def get_recent_commits(
    repo_path: str,
    hours: int,
    author_email: str,
) -> list[dict]:
    """
    Return commit dicts from the given repo within the last ``hours``.

    Args:
        repo_path: Local repository path.
        hours: Lookback window in hours.
        author_email: Optional author email filter.

    Returns:
        List of commit dictionaries.

    Raises:
        None.
    """
    try:
        import git  # type: ignore[import]
    except ImportError:
        console.print("[red][x] GitPython is not installed. Run: pip install gitpython[/red]")
        return []

    repo_name = Path(repo_path).name
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours)

    try:
        repo = git.Repo(repo_path)
    except git.exc.InvalidGitRepositoryError:
        console.print(f"[yellow][!] Not a git repository: {repo_path}[/yellow]")
        return []
    except git.exc.NoSuchPathError:
        console.print(f"[yellow][!] Repo path not found: {repo_path}[/yellow]")
        return []
    except Exception as exc:
        console.print(
            f"[yellow][!] Could not open repo {repo_path}: {sanitize_error_message(exc)}[/yellow]"
        )
        return []

    commits: list[dict] = []

    try:
        for commit in repo.iter_commits():
            committed_at = commit.committed_datetime
            if committed_at < cutoff:
                break

            if author_email and commit.author.email != author_email:
                continue

            files_changed: list[str] = []
            insertions = 0
            deletions = 0

            try:
                if commit.parents:
                    diff = commit.parents[0].diff(commit)
                else:
                    diff = commit.diff(git.NULL_TREE)

                for item in diff:
                    path = item.b_path or item.a_path
                    if path:
                        files_changed.append(path)

                stats = commit.stats.total
                insertions = stats.get("insertions", 0)
                deletions = stats.get("deletions", 0)
            except Exception as exc:
                log_event(
                    "git_diff_failed",
                    repo=repo_name,
                    hash=commit.hexsha[:7],
                    error_type=type(exc).__name__,
                )

            subject = commit.message.strip().splitlines()[0] if commit.message else ""
            commits.append(
                {
                    "repo": repo_name,
                    "hash": commit.hexsha[:7],
                    "message": subject[:MAX_COMMIT_MESSAGE_LENGTH],
                    "timestamp": committed_at.strftime("%Y-%m-%d %H:%M"),
                    "files_changed": files_changed,
                    "insertions": insertions,
                    "deletions": deletions,
                    "modules": _infer_modules(files_changed),
                }
            )

            if len(commits) >= MAX_COMMITS_PER_RUN:
                console.print(
                    f"[yellow][!] Commit count exceeded {MAX_COMMITS_PER_RUN}; truncating to the most recent entries.[/yellow]"
                )
                log_event(
                    "commit_limit_truncated",
                    repo=repo_name,
                    commit_count=len(commits),
                )
                break
    except Exception as exc:
        console.print(
            f"[yellow][!] Error reading commits from {repo_path}: {sanitize_error_message(exc)}[/yellow]"
        )

    return commits[:MAX_COMMITS_PER_RUN]
