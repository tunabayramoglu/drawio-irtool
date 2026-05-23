"""End-to-end converter tests.

For every tests/ir/valid/*.yaml fixture:
- The build pipeline must accept it without exception.
- The output must be parseable XML rooted at <mxfile>.
- The output must contain exactly one mxCell per IR node (vertex) plus
  the two reserved root cells (ids 0 and 1).
- The output must contain at least one mxCell per IR edge (edge=1).

This catches the obvious regressions: missing cells, dangling refs in the
emitted XML, or shape/connector counts that drift from the IR.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from lxml import etree

from irtool.build import ir_to_xml
from irtool.models import IR


FIXTURES = Path(__file__).parent / "ir" / "valid"
VALID = sorted(FIXTURES.glob("*.yaml"))


def _load_ir(path: Path) -> IR:
    return IR.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _count_pseudo_for(items) -> int:  # kept for symmetry with edges
    n = 0
    for it in items:
        if getattr(it, "is_initial", False):
            n += 1
        if getattr(it, "is_final", False):
            n += 1
    return n


def _count_nodes(ir: IR) -> int:
    """Count IR-declared nodes only. Synthetic cells (header text,
    pseudo-states, activation bars) get filtered out in the test by
    ignoring ids that start with ``__``."""
    d = ir.diagram
    if hasattr(d, "entities"):
        return len(d.entities)
    if hasattr(d, "classes"):
        return len(d.classes)
    if hasattr(d, "states"):
        return len(d.states)
    if hasattr(d, "objects"):
        return len(d.objects)
    if hasattr(d, "activities"):
        return len(d.activities) + len(d.swimlanes)
    if hasattr(d, "dialogs"):
        return len(d.dialogs)
    raise AssertionError(f"unknown diagram shape: {type(d).__name__}")


def _count_edges(ir: IR) -> int:
    d = ir.diagram
    base = 0
    for attr in ("flows", "relationships", "transitions", "messages"):
        if hasattr(d, attr):
            base = len(getattr(d, attr))
    # Each pseudo-state contributes one extra connecting edge.
    if hasattr(d, "states"):
        base += _count_pseudo_for(d.states)
    if hasattr(d, "dialogs"):
        base += _count_pseudo_for(d.dialogs)
    return base


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_build_produces_valid_xml(path: Path) -> None:
    ir = _load_ir(path)
    xml = ir_to_xml(ir)
    root = etree.fromstring(xml.encode("utf-8"))
    assert root.tag == "mxfile"
    cells = root.findall(".//mxCell")
    assert len(cells) >= 2, "missing reserved root cells"


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_build_emits_one_vertex_per_node(path: Path) -> None:
    ir = _load_ir(path)
    xml = ir_to_xml(ir)
    root = etree.fromstring(xml.encode("utf-8"))
    # Skip synthetic helper cells (header text, pseudo-states, activation
    # bars). Their ids always start with double underscore.
    vertex_cells = [
        c for c in root.findall(".//mxCell[@vertex='1']")
        if not (c.get("id") or "").startswith("__")
    ]
    assert len(vertex_cells) == _count_nodes(ir), (
        f"{path.name}: expected {_count_nodes(ir)} IR vertex cells, "
        f"got {len(vertex_cells)}"
    )


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_build_emits_one_edge_per_link(path: Path) -> None:
    ir = _load_ir(path)
    xml = ir_to_xml(ir)
    root = etree.fromstring(xml.encode("utf-8"))
    edge_cells = root.findall(".//mxCell[@edge='1']")
    assert len(edge_cells) == _count_edges(ir), (
        f"{path.name}: expected {_count_edges(ir)} edge cells, "
        f"got {len(edge_cells)}"
    )


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_build_edge_endpoints_resolve(path: Path) -> None:
    ir = _load_ir(path)
    xml = ir_to_xml(ir)
    root = etree.fromstring(xml.encode("utf-8"))
    # Vertex set includes synthetic cells (pseudo-states, activations)
    # because real connectors do reference them.
    vertex_ids = {c.get("id") for c in root.findall(".//mxCell[@vertex='1']")}
    vertex_ids.update({"0", "1"})
    for edge in root.findall(".//mxCell[@edge='1']"):
        for end in ("source", "target"):
            ref = edge.get(end)
            assert ref in vertex_ids, (
                f"{path.name}: edge {edge.get('id')!r} references {end}="
                f"{ref!r} which has no corresponding vertex"
            )
