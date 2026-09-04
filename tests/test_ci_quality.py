"""Meta-tests that enforce code quality invariants."""

import ast
import pathlib
import re

import pytest


def test_no_print_in_production_code():
    production_files = list(pathlib.Path("standup").rglob("*.py"))
    violations = []
    for file_path in production_files:
        if file_path.name.startswith("test_"):
            continue
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
            ):
                violations.append(f"{file_path}:{node.lineno}")
    assert violations == [], f"Plain print() found in production code: {violations}"


def test_no_fstring_sql():
    history_file = pathlib.Path("standup/history.py")
    source = history_file.read_text(encoding="utf-8")
    pattern = re.compile(r'f["\'].*?(SELECT|INSERT|UPDATE|DELETE|CREATE)', re.IGNORECASE)
    matches = pattern.findall(source)
    assert matches == [], f"f-string SQL found in history.py: {matches}"


def test_no_raw_exception_messages_in_console_print():
    production_files = list(pathlib.Path("standup").rglob("*.py"))
    for file_path in production_files:
        source = file_path.read_text(encoding="utf-8")
        if (
            "console.print" in source
            and "{exc}" in source
            and "sanitize_error_message" not in source
        ):
            pytest.fail(f"{file_path} uses {{exc}} in console.print without sanitize_error_message")


def test_all_new_modules_have_docstrings():
    production_files = list(pathlib.Path("standup").rglob("*.py"))
    missing = []
    for file_path in production_files:
        if file_path.name == "__init__.py":
            continue
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
        if not (
            tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
        ):
            missing.append(str(file_path))
    assert missing == [], f"Modules missing docstrings: {missing}"


def test_validator_is_single_source_of_truth():
    validation_pattern = re.compile(
        r"re\.match|re\.fullmatch|re\.compile.*@.*\.|\.endswith\(['\"]\.git['\"]"
    )
    violations = []
    for file_path in pathlib.Path("standup").rglob("*.py"):
        if file_path.name in ("validator.py", "security.py"):
            continue
        if file_path.parent.name == "security":
            continue  # redaction regex lives in the security package by design
        source = file_path.read_text(encoding="utf-8")
        for index, line in enumerate(source.splitlines(), 1):
            if validation_pattern.search(line):
                violations.append(f"{file_path}:{index}: {line.strip()}")
    assert violations == [], "Validation logic outside validator.py:\n" + "\n".join(violations)
