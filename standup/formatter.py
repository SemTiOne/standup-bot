"""
formatter.py - Structure commit data into a prompt string for the LLM.
"""

from standup.security import redact_sensitive_patterns


def format_commits_for_prompt(commits: list[dict]) -> str:
    """
    Build a structured summary string from a list of commit dicts.

    Groups commits by repo, includes commit type context, and returns the full
    prompt text ready to send to the LLM.
    """
    if not commits:
        return ""

    by_repo: dict[str, list[dict]] = {}
    for commit in commits:
        by_repo.setdefault(commit["repo"], []).append(commit)

    lines: list[str] = []

    total_commits = len(commits)
    total_insertions = sum(commit.get("insertions", 0) for commit in commits)
    total_deletions = sum(commit.get("deletions", 0) for commit in commits)
    all_modules = set()
    for commit in commits:
        all_modules.update(commit.get("modules", []))

    for repo, repo_commits in by_repo.items():
        lines.append(f"REPO: {repo}")
        for commit in repo_commits:
            time_str = commit.get("timestamp", "")[-5:]
            message = redact_sensitive_patterns(commit.get("message", ""))
            files = commit.get("files_changed", [])
            insertions = commit.get("insertions", 0)
            deletions = commit.get("deletions", 0)
            commit_type = commit.get("type", "unknown")
            commit_emoji = commit.get("type_emoji", "")

            file_str = ", ".join(files[:5])
            if len(files) > 5:
                file_str += f" (+{len(files) - 5} more)"

            emoji_prefix = f"{commit_emoji} " if commit_emoji else ""
            line = f"- [{time_str}] {emoji_prefix}({commit_type}) {message}".strip()
            if file_str:
                line += f" -> files: {file_str}"
            line += f" (+{insertions}/-{deletions})"
            lines.append(line)
        lines.append("")

    lines.append(
        f"SUMMARY: {total_commits} commit(s), +{total_insertions}/-{total_deletions} lines, modules: {', '.join(sorted(all_modules)) or 'n/a'}"
    )

    return "\n".join(lines)


def build_standup_prompt(formatted_commits: str, tone: str) -> str:
    """Wrap formatted commits in the final prompt for the LLM."""
    tone_instruction = (
        "Use a casual, friendly tone." if tone == "casual" else "Use a formal, professional tone."
    )
    return (
        "Here is my recent git activity:\n\n"
        f"{formatted_commits}\n\n"
        "Please generate a daily standup summary from this data. "
        "Pay attention to the commit type labels so features, fixes, refactors, and supporting work are described accurately. "
        f"{tone_instruction} "
        "Format it as:\n"
        "**Yesterday:** what I worked on\n"
        "**Today:** what I plan to do\n"
        "**Blockers:** any blockers (or 'None')\n"
    )
