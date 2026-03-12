"""
git_reader.py — Git log parsing logic.

Reads recent commits from one or more local git repositories.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from rich.console import Console

console = Console()


def _infer_modules(files: List[str]) -> List[str]:
    """Infer top-level module names from a list of file paths."""
    modules = set()
    for f in files:
        parts = Path(f).parts
        if len(parts) >= 2:
            modules.add(parts[1])  # second segment
        elif len(parts) == 1:
            modules.add(parts[0])  # top-level file, use file name
    return sorted(modules)


def get_recent_commits(
    repo_path: str,
    hours: int,
    author_email: str,
) -> List[dict]:
    """
    Return a list of commit dicts from the given repo within the last `hours`.

    Each commit dict contains:
        repo, hash, message, timestamp, files_changed, insertions, deletions, modules
    """
    try:
        import git  # type: ignore[import]
    except ImportError:
        console.print(
            "[red]❌ GitPython is not installed. Run: pip install gitpython[/red]"
        )
        return []

    repo_name = Path(repo_path).name
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours)

    try:
        repo = git.Repo(repo_path)
    except git.exc.InvalidGitRepositoryError:
        console.print(f"[yellow]⚠️  Not a git repository: {repo_path}[/yellow]")
        return []
    except git.exc.NoSuchPathError:
        console.print(f"[yellow]⚠️  Repo path not found: {repo_path}[/yellow]")
        return []
    except Exception as exc:
        console.print(f"[yellow]⚠️  Could not open repo {repo_path}: {exc}[/yellow]")
        return []

    commits: List[dict] = []

    try:
        for commit in repo.iter_commits():
            # committed_datetime is timezone-aware
            committed_at = commit.committed_datetime
            if committed_at < cutoff:
                break

            # Filter by author email if set
            if author_email and commit.author.email != author_email:
                continue

            # Collect changed files and stats
            files_changed: List[str] = []
            insertions = 0
            deletions = 0

            try:
                if commit.parents:
                    diff = commit.parents[0].diff(commit)
                else:
                    # Initial commit — diff against empty tree
                    diff = commit.diff(git.NULL_TREE)

                for item in diff:
                    path = item.b_path or item.a_path
                    if path:
                        files_changed.append(path)

                stats = commit.stats.total
                insertions = stats.get("insertions", 0)
                deletions = stats.get("deletions", 0)
            except Exception:
                pass  # stats failure is non-fatal

            commits.append(
                {
                    "repo": repo_name,
                    "hash": commit.hexsha[:7],
                    "message": commit.message.strip().splitlines()[0],
                    "timestamp": committed_at.strftime("%Y-%m-%d %H:%M"),
                    "files_changed": files_changed,
                    "insertions": insertions,
                    "deletions": deletions,
                    "modules": _infer_modules(files_changed),
                }
            )
    except Exception as exc:
        console.print(f"[yellow]⚠️  Error reading commits from {repo_path}: {exc}[/yellow]")

    return commits