"""Convert a validated IR into a drawio XML document.

Pipeline:
    IR (Pydantic) -> per-type build() -> (shapes, connectors, canvas)
                                       -> emit() -> drawio XML string

Each per-type module owns sizing + layout + style for its diagram type.
The XML emitter is shared and has no geometry logic.
"""

from __future__ import annotations

from ..models import (
    IR,
    ActivityDiagram,
    ClassDiagram,
    DFDDiagram,
    DialogDiagram,
    SequenceDiagram,
    StateDiagram,
)
from . import activity, class_, dfd, dialog, sequence, state
from .types import BuildResult
from .xml_emit import emit_xml


def build(ir: IR) -> BuildResult:
    """Run the type-specific builder for this IR."""
    d = ir.diagram
    if isinstance(d, DFDDiagram):
        result = dfd.build(d)
    elif isinstance(d, ClassDiagram):
        result = class_.build(d)
    elif isinstance(d, StateDiagram):
        result = state.build(d)
    elif isinstance(d, SequenceDiagram):
        result = sequence.build(d)
    elif isinstance(d, ActivityDiagram):
        result = activity.build(d)
    elif isinstance(d, DialogDiagram):
        result = dialog.build(d)
    else:
        raise TypeError(f"no builder for diagram type {type(d).__name__}")
    # Carry description from the IR through to the emitter so it can
    # render the header strip uniformly across all diagram types.
    result.description = getattr(d, "description", None)
    return result


def ir_to_xml(ir: IR) -> str:
    """End-to-end: validated IR -> drawio XML string."""
    return emit_xml(build(ir))
