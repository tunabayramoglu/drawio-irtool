"""Sweep tests/ir/{valid,invalid} fixtures through the validator.

Pattern:
- tests/ir/valid/X.yaml         -> must produce zero ERROR issues.
- tests/ir/invalid/X.yaml       -> must produce >=1 ERROR and every code
                                   listed in X.expected.json must appear.

Adding a new fixture is purely additive: drop the YAML in, optionally
write the .expected.json next to it. No test code changes required.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from irtool.issues import Severity
from irtool.validate import validate_path


FIXTURES = Path(__file__).parent / "ir"
VALID_DIR = FIXTURES / "valid"
INVALID_DIR = FIXTURES / "invalid"

VALID_FIXTURES = sorted(VALID_DIR.glob("*.yaml"))
INVALID_FIXTURES = sorted(INVALID_DIR.glob("*.yaml"))


def _fmt(issues) -> str:
    return "\n  ".join(i.format() for i in issues) or "<none>"


@pytest.mark.parametrize("path", VALID_FIXTURES, ids=lambda p: p.name)
def test_valid_fixture_has_no_errors(path: Path) -> None:
    issues = validate_path(path)
    errors = [i for i in issues if i.severity == Severity.ERROR]
    assert not errors, (
        f"{path.name} produced unexpected errors:\n  {_fmt(errors)}"
    )


@pytest.mark.parametrize("path", INVALID_FIXTURES, ids=lambda p: p.name)
def test_invalid_fixture_matches_expected(path: Path) -> None:
    expected_path = path.with_suffix(".expected.json")
    assert expected_path.exists(), (
        f"missing expected spec next to {path.name}: {expected_path.name}"
    )
    spec = json.loads(expected_path.read_text(encoding="utf-8"))
    required = set(spec.get("codes", []))
    assert required, (
        f"{expected_path.name} must list at least one required code in 'codes'"
    )

    issues = validate_path(path)
    actual = {i.code.value for i in issues}
    missing = required - actual
    assert not missing, (
        f"{path.name}: expected codes missing.\n"
        f"  required: {sorted(required)}\n"
        f"  actual:   {sorted(actual)}\n"
        f"  issues:\n  {_fmt(issues)}"
    )

    errors = [i for i in issues if i.severity == Severity.ERROR]
    assert errors, (
        f"{path.name}: expected at least one ERROR-level issue, got only "
        f"warnings/none.\n  issues:\n  {_fmt(issues)}"
    )
