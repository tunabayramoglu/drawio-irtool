from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class IssueCode(str, Enum):
    # Parse/schema layer
    YAML_PARSE = "yaml_parse"
    SCHEMA_VIOLATION = "schema_violation"
    NOT_A_MAPPING = "not_a_mapping"

    # Common semantic
    DUPLICATE_ID = "duplicate_id"
    DANGLING_REF = "dangling_ref"
    ORPHAN_NODE = "orphan_node"
    EMPTY_DIAGRAM = "empty_diagram"
    SELF_LOOP_FORBIDDEN = "self_loop_forbidden"

    # DFD
    DFD_STORE_TO_STORE = "dfd_store_to_store"
    DFD_EXTERNAL_TO_STORE = "dfd_external_to_store"
    DFD_STORE_TO_EXTERNAL = "dfd_store_to_external"
    DFD_EXTERNAL_TO_EXTERNAL = "dfd_external_to_external"

    # Class
    INHERITANCE_CYCLE = "inheritance_cycle"
    MULTIPLE_INHERITANCE = "multiple_inheritance"

    # State
    NO_INITIAL_STATE = "no_initial_state"
    MULTIPLE_INITIAL_STATES = "multiple_initial_states"
    NO_FINAL_STATE = "no_final_state"
    UNREACHABLE_STATE = "unreachable_state"

    # Sequence
    SEQ_OBJECT_ORDER = "seq_object_order"

    # Activity
    ACTIVITY_UNKNOWN_SWIMLANE = "activity_unknown_swimlane"
    NO_START_ACTIVITY = "no_start_activity"
    MULTIPLE_START_ACTIVITIES = "multiple_start_activities"
    NO_END_ACTIVITY = "no_end_activity"


class Issue(BaseModel):
    model_config = ConfigDict(frozen=True)

    severity: Severity
    code: IssueCode
    path: str
    message: str

    def format(self) -> str:
        return f"[{self.severity.value}] {self.code.value} at {self.path}: {self.message}"


def error(code: IssueCode, path: str, message: str) -> Issue:
    return Issue(severity=Severity.ERROR, code=code, path=path, message=message)


def warning(code: IssueCode, path: str, message: str) -> Issue:
    return Issue(severity=Severity.WARNING, code=code, path=path, message=message)


def schema_violation(loc: tuple[Any, ...], message: str) -> Issue:
    path = ".".join(str(p) for p in loc) if loc else "<root>"
    return Issue(
        severity=Severity.ERROR,
        code=IssueCode.SCHEMA_VIOLATION,
        path=path,
        message=message,
    )
