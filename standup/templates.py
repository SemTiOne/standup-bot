"""
templates.py - Render and validate customizable standup output templates.

This module provides a bounded placeholder renderer and a tolerant parser for
LLM standup output so users can reshape the final summary without extra
dependencies.
"""

import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from standup.validator import (
    MAX_RENDERED_TEMPLATE_LENGTH,
    MAX_TEMPLATE_LENGTH,
    MAX_VARIABLE_VALUE_LENGTH,
    VALID_TEMPLATE_VARIABLES,
    validate_template_string,
)

BUILTIN_TEMPLATES = {
    "default": """**Yesterday:** {yesterday}
**Today:** {today}
**Blockers:** {blockers}""",
    "slack": """:calendar: *Daily Standup - {date}*
:white_check_mark: *Yesterday:* {yesterday}
:rocket: *Today:* {today}
:warning: *Blockers:* {blockers}""",
    "minimal": """{yesterday} -> {today}. Blockers: {blockers}""",
    "detailed": """## Daily Standup - {date}

### ✅ Yesterday
{yesterday}

### 🎯 Today
{today}

### 🚧 Blockers
{blockers}

### 📊 Stats
- Commits: {commit_count}
- Repos: {repos}
- Provider: {provider}""",
    "jira": """[Yesterday] {yesterday}
[Today] {today}
[Impediments] {blockers}""",
}

TEMPLATE_VARIABLES = tuple(VALID_TEMPLATE_VARIABLES)
_MAX_TEMPLATE_LENGTH = MAX_TEMPLATE_LENGTH
_MAX_RENDERED_LENGTH = MAX_RENDERED_TEMPLATE_LENGTH
_MAX_VARIABLE_VALUE_LENGTH = MAX_VARIABLE_VALUE_LENGTH
_ALLOWED_VARIABLES = frozenset(VALID_TEMPLATE_VARIABLES)
_SECTION_HEADER_RE = re.compile(
    r"^\s*(?:[*#>\-\s]*)?(?:\[\s*)?(yesterday|today|blockers|impediments)"
    r"(?:\s*\])?(?:\s*[:\-])?\s*(.*)$",
    re.IGNORECASE,
)


def list_templates(custom_templates: Optional[Dict[str, str]] = None) -> List[str]:
    """
    List available built-in and custom template names.

    Args:
        custom_templates: Optional mapping of user template names to template text.

    Returns:
        Sorted list of template names.

    Raises:
        None.
    """
    names = set(BUILTIN_TEMPLATES.keys())
    if isinstance(custom_templates, dict):
        names.update(custom_templates.keys())
    return sorted(names)


def get_template(name: str, custom_templates: Optional[Dict[str, str]] = None) -> str:
    """
    Retrieve a built-in or custom template by name.

    Args:
        name: Template name to resolve.
        custom_templates: Optional custom template mapping.

    Returns:
        Template string.

    Raises:
        ValueError: If the requested template name is unknown.
    """
    if isinstance(custom_templates, dict) and name in custom_templates:
        return custom_templates[name]
    if name in BUILTIN_TEMPLATES:
        return BUILTIN_TEMPLATES[name]
    raise ValueError("Unknown template: {0}".format(name))


def parse_llm_output(standup_text: str) -> Dict[str, str]:
    """
    Extract Yesterday, Today, and Blockers sections from LLM output.

    Args:
        standup_text: Raw standup text returned by the LLM.

    Returns:
        Dict with ``yesterday``, ``today``, and ``blockers`` keys.

    Raises:
        None.
    """
    result = {"yesterday": "", "today": "", "blockers": ""}
    current_key: Optional[str] = None

    for raw_line in (standup_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            if current_key and result[current_key]:
                result[current_key] = result[current_key].rstrip() + "\n"
            continue

        header_match = _SECTION_HEADER_RE.match(line)
        if header_match:
            section = header_match.group(1).lower()
            remainder = header_match.group(2).strip().strip("*").strip()
            current_key = "blockers" if section == "impediments" else section
            if remainder:
                result[current_key] = remainder
            continue

        if current_key:
            separator = "\n" if result[current_key] and not result[current_key].endswith("\n") else ""
            result[current_key] += separator + line

    for key, fallback in (("yesterday", ""), ("today", ""), ("blockers", "None")):
        value = result.get(key, "")
        value = value.replace("\n\n", "\n").strip()
        result[key] = value or fallback

    if not any(result.values()):
        result["yesterday"] = (standup_text or "").strip()
        result["today"] = ""
        result["blockers"] = "None"
    elif result["yesterday"] == "" and (standup_text or "").strip():
        result["yesterday"] = (standup_text or "").strip()

    return result


def render_template(template_str: str, variables: Dict[str, object]) -> str:
    """
    Safely render a template using allowlisted placeholder replacement.

    Args:
        template_str: Template text containing placeholders.
        variables: Mapping of placeholder names to replacement values.

    Returns:
        Rendered template string with unknown placeholders left unchanged.

    Raises:
        None.
    """
    try:
        rendered = "" if template_str is None else str(template_str)
        if len(rendered) > _MAX_TEMPLATE_LENGTH:
            rendered = rendered[:_MAX_TEMPLATE_LENGTH]
        safe_variables = variables if isinstance(variables, dict) else {}

        for key in _ALLOWED_VARIABLES:
            if key not in safe_variables:
                continue
            raw_value = safe_variables.get(key)
            value = "" if raw_value is None else str(raw_value)
            value = value[:_MAX_VARIABLE_VALUE_LENGTH]
            rendered = rendered.replace("{" + key + "}", value)
        return rendered[:_MAX_RENDERED_LENGTH]
    except Exception:
        try:
            fallback = "" if template_str is None else str(template_str)
            return fallback[:_MAX_RENDERED_LENGTH]
        except Exception:
            return ""


def build_template_variables(
    standup_text: str,
    commit_count: int,
    repos: List[str],
    provider: str,
    author_email: str,
    now: Optional[datetime] = None,
) -> Dict[str, str]:
    """
    Build the full variable map used by template rendering.

    Args:
        standup_text: Raw standup text from the LLM.
        commit_count: Number of commits included in the standup.
        repos: Repository names included in the run.
        provider: Provider name used for generation.
        author_email: Configured author email filter.
        now: Optional timestamp override for deterministic tests.

    Returns:
        Dict containing all supported template variables.

    Raises:
        None.
    """
    timestamp = now or datetime.now()
    parsed = parse_llm_output(standup_text)
    parsed.update(
        {
            "date": timestamp.strftime("%Y-%m-%d"),
            "time": timestamp.strftime("%H:%M"),
            "commit_count": str(commit_count),
            "repos": ", ".join(repos),
            "provider": provider,
            "author_email": author_email,
        }
    )
    return parsed


def validate_custom_template(template_str: str) -> Tuple[bool, str]:
    """
    Validate a custom template string.

    Args:
        template_str: Template text to validate.

    Returns:
        Tuple of ``(is_valid, message)``.

    Raises:
        None.
    """
    return validate_template_string(template_str)
