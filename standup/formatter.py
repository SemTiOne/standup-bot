"""
formatter.py — Structures commit data into a human-readable prompt string for the LLM.
"""

from typing import List

from standup.security import redact_sensitive_patterns


def format_commits_for_prompt(commits: List[dict]) -> str:
    """
    Build a structured summary string from a list of commit dicts.

    Groups commits by repo and includes stats. Returns the full prompt
    text ready to send to the LLM.
    """
    if not commits:
        return ""

    # Group by repo
    by_repo: dict = {}
    for c in commits:
        by_repo.setdefault(c["repo"], []).append(c)

    lines: List[str] = []

    total_commits = len(commits)
    total_insertions = sum(c.get("insertions", 0) for c in commits)
    total_deletions = sum(c.get("deletions", 0) for c in commits)
    all_modules: set = set()
    for c in commits:
        all_modules.update(c.get("modules", []))

    for repo, repo_commits in by_repo.items():
        lines.append(f"REPO: {repo}")
        for c in repo_commits:
            time_str = c.get("timestamp", "")[-5:]  # HH:MM
            message = redact_sensitive_patterns(c.get("message", ""))
            files = c.get("files_changed", [])
            ins = c.get("insertions", 0)
            dels = c.get("deletions", 0)

            file_str = ", ".join(files[:5])
            if len(files) > 5:
                file_str += f" (+{len(files) - 5} more)"

            line = f"- [{time_str}] {message}"
            if file_str:
                line += f" → files: {file_str}"
            line += f" (+{ins}/-{dels})"
            lines.append(line)
        lines.append("")

    # Summary footer
    lines.append(
        f"SUMMARY: {total_commits} commit(s), "
        f"+{total_insertions}/-{total_deletions} lines, "
        f"modules: {', '.join(sorted(all_modules)) or 'n/a'}"
    )

    return "\n".join(lines)


def build_standup_prompt(formatted_commits: str, tone: str) -> str:
    """Wrap formatted commits in the final prompt for the LLM."""
    tone_instruction = (
        "Use a casual, friendly tone." if tone == "casual" else "Use a formal, professional tone."
    )
    return (
        f"Here is my recent git activity:\n\n"
        f"{formatted_commits}\n\n"
        f"Please generate a daily standup summary from this data. "
        f"{tone_instruction} "
        f"Format it as:\n"
        f"**Yesterday:** what I worked on\n"
        f"**Today:** what I plan to do\n"
        f"**Blockers:** any blockers (or 'None')\n"
    )