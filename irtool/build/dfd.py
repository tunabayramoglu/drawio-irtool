"""DFD: 3-column layout by entity type (external -> process -> store).

Each type forms a column; if a column would have more than _MAX_PER_COL
entities, it wraps into multiple sub-columns so the diagram never grows
unboundedly tall. Sub-columns push subsequent column types to the right.

Edge routing is intentionally minimal — drawio's default orthogonal
router handles every edge. Bidirectional pairs get parallel-track
separation via the shared helper.
"""

from __future__ import annotations

from ..models import DFDDiagram, DFDEntity
from ._common import EDGE_STYLE, find_bidirectional, make_connector, parallel_track
from .types import BuildResult, Shape


_ENTITY_STYLE = {
    "external_entity": (
        "rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;"
        "strokeColor=#6c8ebf;fontSize=13;"
    ),
    "process": (
        "rounded=1;arcSize=20;whiteSpace=wrap;html=1;fillColor=#fff2cc;"
        "strokeColor=#d6b656;fontSize=13;"
    ),
    "store": (
        "rounded=0;whiteSpace=wrap;html=1;fillColor=#e1d5e7;"
        "strokeColor=#9673a6;fontSize=13;"
    ),
}

_W, _H = 200, 80
_V_GAP = 50
_H_GAP = 100         # space between sub-columns of the same type
_TYPE_GAP = 160      # space between different column types
_TOP_MARGIN = 60
_LEFT_MARGIN = 60
_RIGHT_MARGIN = 60
_BOTTOM_MARGIN = 60

# Maximum entities stacked vertically in a single sub-column before wrapping.
_MAX_PER_COL = 6


_COL_ORDER = ("external_entity", "process", "store")


def build(d: DFDDiagram) -> BuildResult:
    columns: dict[str, list[DFDEntity]] = {ct: [] for ct in _COL_ORDER}
    for e in d.entities:
        columns[e.type].append(e)

    shapes: list[Shape] = []
    positions: dict[str, tuple[float, float]] = {}
    max_bottom = _TOP_MARGIN

    cur_x = _LEFT_MARGIN
    for col_type in _COL_ORDER:
        members = columns[col_type]
        if not members:
            continue
        sub_columns = [
            members[i : i + _MAX_PER_COL]
            for i in range(0, len(members), _MAX_PER_COL)
        ]
        for sub in sub_columns:
            y = _TOP_MARGIN
            for entity in sub:
                shapes.append(
                    Shape(
                        id=entity.id,
                        x=cur_x,
                        y=y,
                        width=_W,
                        height=_H,
                        label=entity.name or entity.id,
                        style=_ENTITY_STYLE[col_type],
                    )
                )
                positions[entity.id] = (cur_x, y)
                y += _H + _V_GAP
            max_bottom = max(max_bottom, y)
            cur_x += _W + _H_GAP
        cur_x += _TYPE_GAP - _H_GAP

    bidir = find_bidirectional(d.flows)
    connectors = []
    for idx, flow in enumerate(d.flows):
        track = None
        if (flow.src, flow.dst) in bidir:
            sx, sy = positions[flow.src]
            tx, ty = positions[flow.dst]
            track = parallel_track(flow.src, flow.dst, sx, tx, sy, ty)
        connectors.append(
            make_connector(idx, flow.src, flow.dst, flow.label, EDGE_STYLE, track)
        )

    canvas_w = int(cur_x - _TYPE_GAP + _RIGHT_MARGIN)
    canvas_h = max_bottom + _BOTTOM_MARGIN - _V_GAP

    return BuildResult(
        title=d.title,
        shapes=shapes,
        connectors=connectors,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
    )
