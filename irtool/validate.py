"""Top-level validation pipeline: YAML -> schema -> semantic.

A single entry point so the CLI, the MCP server, and the future renderer
all run the exact same checks in the exact same order.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from .issues import Issue, IssueCode, Severity, error, schema_violation
from .models import IR
from .semantic import check as semantic_check


def validate_path(path: Path | str) -> list[Issue]:
    """Validate an IR YAML file. Returns issues in stable order."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return [error(IssueCode.YAML_PARSE, str(path), f"cannot read file: {e}")]
    return validate_text(text)


def validate_text(text: str) -> list[Issue]:
    """Validate IR YAML provided as a string."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return [error(IssueCode.YAML_PARSE, "<root>", str(e))]

    if data is None:
        return [error(IssueCode.YAML_PARSE, "<root>", "file is empty")]
    if not isinstance(data, dict):
        return [
            error(
                IssueCode.NOT_A_MAPPING,
                "<root>",
                f"top-level must be a mapping, got {type(data).__name__}",
            )
        ]

    try:
        ir = IR.model_validate(data)
    except ValidationError as e:
        return [schema_violation(err["loc"], err["msg"]) for err in e.errors()]

    return semantic_check(ir)


def parse_and_validate(text: str) -> tuple[list[Issue], "IR | None"]:
    """Validate IR YAML and return both issues and the parsed IR object.

    Returns (issues, ir) where ir is None if any schema-level error
    prevented parsing, or the validated IR instance on success. Semantic
    warnings are included in issues even when ir is returned.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return [error(IssueCode.YAML_PARSE, "<root>", str(e))], None

    if data is None:
        return [error(IssueCode.YAML_PARSE, "<root>", "file is empty")], None
    if not isinstance(data, dict):
        return (
            [
                error(
                    IssueCode.NOT_A_MAPPING,
                    "<root>",
                    f"top-level must be a mapping, got {type(data).__name__}",
                )
            ],
            None,
        )

    try:
        ir = IR.model_validate(data)
    except ValidationError as e:
        return [schema_violation(err["loc"], err["msg"]) for err in e.errors()], None

    semantic_issues = semantic_check(ir)
    return semantic_issues, ir


def summarize(issues: list[Issue]) -> tuple[int, int]:
    """Return (error_count, warning_count)."""
    errors = sum(1 for i in issues if i.severity == Severity.ERROR)
    warnings = sum(1 for i in issues if i.severity == Severity.WARNING)
    return errors, warnings
