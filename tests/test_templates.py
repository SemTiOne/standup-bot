"""Tests for standup/templates.py."""

from datetime import datetime

import pytest

from standup.templates import (
    BUILTIN_TEMPLATES,
    _MAX_RENDERED_LENGTH,
    _MAX_VARIABLE_VALUE_LENGTH,
    build_template_variables,
    get_template,
    list_templates,
    parse_llm_output,
    render_template,
    validate_custom_template,
)


def test_list_templates_contains_default():
    assert "default" in list_templates()


def test_list_templates_includes_custom_names():
    assert "team" in list_templates({"team": "Done: {yesterday}"})


def test_get_template_builtin():
    assert get_template("slack") == BUILTIN_TEMPLATES["slack"]


def test_get_template_custom():
    assert get_template("team", {"team": "Done: {yesterday}"}) == "Done: {yesterday}"


def test_get_template_unknown_raises():
    with pytest.raises(ValueError):
        get_template("missing")


def test_parse_llm_output_handles_bold_headers():
    parsed = parse_llm_output("**Yesterday:** shipped cache\n**Today:** write tests\n**Blockers:** none")
    assert parsed["yesterday"] == "shipped cache"
    assert parsed["today"] == "write tests"
    assert parsed["blockers"] == "none"


def test_parse_llm_output_handles_markdown_sections():
    parsed = parse_llm_output("## Yesterday\nDid one\n## Today\nDo two\n## Blockers\nNeed review")
    assert "Did one" in parsed["yesterday"]
    assert "Do two" in parsed["today"]
    assert "Need review" in parsed["blockers"]


def test_parse_llm_output_handles_jira_style_impediments():
    parsed = parse_llm_output("[Yesterday] done\n[Today] next\n[Impediments] waiting")
    assert parsed["blockers"] == "waiting"


def test_render_template_leaves_unknown_variables_as_is():
    rendered = render_template("Done: {yesterday} {mystery}", {"yesterday": "cache"})
    assert rendered == "Done: cache {mystery}"


def test_render_template_does_not_execute_import_like_variable():
    rendered = render_template("{__import__('os').system('rm -rf /')}", {"yesterday": "cache"})
    assert "__import__" in rendered


def test_render_template_truncates_variable_values():
    rendered = render_template(
        "Done: {yesterday}",
        {"yesterday": "x" * (_MAX_VARIABLE_VALUE_LENGTH + 10)},
    )
    assert len(rendered.split("Done: ", 1)[1]) == _MAX_VARIABLE_VALUE_LENGTH


def test_render_template_truncates_rendered_output():
    rendered = render_template(
        "{yesterday}{today}{blockers}",
        {
            "yesterday": "x" * _MAX_VARIABLE_VALUE_LENGTH,
            "today": "y" * _MAX_VARIABLE_VALUE_LENGTH,
            "blockers": "z" * _MAX_VARIABLE_VALUE_LENGTH,
        },
    )
    assert len(rendered) == _MAX_RENDERED_LENGTH


def test_build_template_variables_includes_metadata():
    variables = build_template_variables(
        "**Yesterday:** done\n**Today:** next\n**Blockers:** none",
        commit_count=3,
        repos=["api", "web"],
        provider="ollama",
        author_email="dev@example.com",
        now=datetime(2026, 4, 26, 9, 30),
    )
    assert variables["date"] == "2026-04-26"
    assert variables["time"] == "09:30"
    assert variables["commit_count"] == "3"
    assert variables["repos"] == "api, web"


def test_validate_custom_template_accepts_valid_template():
    ok, message = validate_custom_template("Done: {yesterday}")
    assert ok, message


def test_validate_custom_template_rejects_empty_template():
    ok, _ = validate_custom_template("")
    assert not ok


def test_validate_custom_template_rejects_oversized_template():
    ok, _ = validate_custom_template("{yesterday}" + ("x" * 2100))
    assert not ok


def test_validate_custom_template_rejects_format_spec():
    ok, _ = validate_custom_template("Done: {yesterday!r}")
    assert not ok


def test_validate_custom_template_rejects_alignment_spec():
    ok, _ = validate_custom_template("Done: {yesterday:>10}")
    assert not ok


def test_validate_custom_template_rejects_attribute_access():
    ok, _ = validate_custom_template("Done: {yesterday.__class__}")
    assert not ok


def test_validate_custom_template_rejects_disallowed_only_variables():
    ok, _ = validate_custom_template("Done: {mystery}")
    assert not ok
