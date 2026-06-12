"""DFD: 3-column layout by entity type (external -> process -> store).

Each type forms a column; if a column would have more than _MAX_PER_COL
entities, it wraps into multiple sub-columns so the diagram never grows
unboundedly tall. Sub-columns push subsequent column types to the right.

Edge routing is intentionally minimal — drawio's default orthogonal
router handles every edge. Bidirectional pairs get parallel-track
separation via the shared helper.
"""

from __future__ import annotations

from ..models import DFDDiagram, DFDEntity, DFDAnnotation
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
    _COL_KEY = {"external_entity": 0, "process": 1, "store": 2}
    col_entities: dict[int, list[tuple[float, float]]] = {}
    for eid, (x, _y) in positions.items():
        entity = next(e for e in d.entities if e.id == eid)
        k = _COL_KEY[entity.type]
        col_entities.setdefault(k, []).append((x, x + _W))

    col_range: dict[int, tuple[float, float]] = {}
    for k, rects in col_entities.items():
        col_range[k] = (min(r[0] for r in rects), max(r[1] for r in rects))

    row_of: dict[str, int] = {}
    for eid, (_x, y) in positions.items():
        row_of[eid] = round((y - _TOP_MARGIN) / (_H + _V_GAP))

    def _inter_column_x(src_col: int, dst_col: int) -> float:
        if src_col < dst_col:
            return (col_range[src_col][1] + col_range[dst_col][0]) / 2
        return (col_range[dst_col][1] + col_range[src_col][0]) / 2

    # --- Per-edge slot assignment ---------------------------------------
    # Two-pass: count group totals, then assign per-edge slots stored in
    # _slot_of[flow_idx] = (src_slot, dst_slot).
    _slot_of: dict[int, tuple[int, int]] = {}
    _group_total: dict[tuple[str, str, int], int] = {}
    _group_assigned: dict[tuple[str, str, int], int] = {}

    # Pass 1: count how many edges touch each (entity, side, row).
    for i, flow in enumerate(d.flows):
        if (flow.src, flow.dst) in bidir:
            continue
        se = next(e for e in d.entities if e.id == flow.src)
        de = next(e for e in d.entities if e.id == flow.dst)
        sc = _COL_KEY[se.type]; dc = _COL_KEY[de.type]
        sr = row_of[flow.src]; dr = row_of[flow.dst]
        if sc == dc and abs(dr - sr) <= 1:
            continue
        src_side = "R" if sc < dc else "L"
        dst_side = "L" if sc < dc else "R"
        for key in ((flow.src, src_side, sr), (flow.dst, dst_side, dr)):
            _group_total[key] = _group_total.get(key, 0) + 1

    # Pass 2: assign sequential slots.
    for i, flow in enumerate(d.flows):
        if (flow.src, flow.dst) in bidir:
            continue
        se = next(e for e in d.entities if e.id == flow.src)
        de = next(e for e in d.entities if e.id == flow.dst)
        sc = _COL_KEY[se.type]; dc = _COL_KEY[de.type]
        sr = row_of[flow.src]; dr = row_of[flow.dst]
        if sc == dc and abs(dr - sr) <= 1:
            continue
        src_side = "R" if sc < dc else "L"
        dst_side = "L" if sc < dc else "R"
        key_src = (flow.src, src_side, sr)
        key_dst = (flow.dst, dst_side, dr)
        ss = _group_assigned.get(key_src, 0)
        ds = _group_assigned.get(key_dst, 0)
        _group_assigned[key_src] = ss + 1
        _group_assigned[key_dst] = ds + 1
        _slot_of[i] = (ss, ds)

    def _side_pin(eid: str, side: str, row: int, slot: int) -> float:
        t = _group_total.get((eid, side, row), 1)
        if t <= 1:
            return 0.5
        return (slot + 1) / (t + 1)

    def _route(
        flow: Flow,
        flow_idx: int,
    ) -> tuple[tuple[float, float, float, float] | None, list[tuple[float, float]]]:
        sx, sy = positions[flow.src]
        dx, dy = positions[flow.dst]
        src_my = sy + _H / 2
        dst_my = dy + _H / 2
        se = next(e for e in d.entities if e.id == flow.src)
        de = next(e for e in d.entities if e.id == flow.dst)
        sc = _COL_KEY[se.type]
        dc = _COL_KEY[de.type]
        sr = row_of[flow.src]
        dr = row_of[flow.dst]

        if sc == dc and abs(dr - sr) == 1:
            return None, []

        gutter_x = _inter_column_x(sc, dc)
        slots = _slot_of.get(flow_idx, (0, 0))
        src_slot, dst_slot = slots

        if sc < dc:
            src_side, dst_side = "R", "L"
        else:
            src_side, dst_side = "L", "R"

        exit_pin = (1.0 if src_side == "R" else 0.0,
                    _side_pin(flow.src, src_side, sr, src_slot))
        entry_pin = (0.0 if dst_side == "L" else 1.0,
                     _side_pin(flow.dst, dst_side, dr, dst_slot))

        off_src = (exit_pin[1] - 0.5) * _H
        off_dst = (entry_pin[1] - 0.5) * _H
        track = (exit_pin[0], exit_pin[1], entry_pin[0], entry_pin[1])

        if sr == dr:
            return track, [(gutter_x, src_my + off_src)]
        else:
            return track, [(gutter_x, src_my + off_src),
                           (gutter_x, dst_my + off_dst)]

    connectors = []
    for idx, flow in enumerate(d.flows):
        track = None
        waypoints = None
        if (flow.src, flow.dst) in bidir:
            sx, sy = positions[flow.src]
            tx, ty = positions[flow.dst]
            track = parallel_track(flow.src, flow.dst, sx, tx, sy, ty)
        else:
            track, waypoints = _route(flow, idx)
        c = make_connector(idx, flow.src, flow.dst, flow.label, EDGE_STYLE, track)
        if waypoints:
            c.waypoints = waypoints
        connectors.append(c)

    canvas_w = int(cur_x - _TYPE_GAP + _RIGHT_MARGIN)
    canvas_h = max_bottom + _BOTTOM_MARGIN - _V_GAP

    # --- annotations: dashed rectangles around grouped entities ----------
    _ANN_PAD = 16
    for ann in d.annotations:
        grouped = [eid for eid in ann.entities if eid in positions]
        if not grouped:
            continue
        ann_x = min(positions[eid][0] for eid in grouped) - _ANN_PAD
        ann_y = min(positions[eid][1] for eid in grouped) - _ANN_PAD
        ann_r = max(positions[eid][0] + _W for eid in grouped) + _ANN_PAD
        ann_b = max(positions[eid][1] + _H for eid in grouped) + _ANN_PAD
        ann_style = (
            f"rounded=0;whiteSpace=wrap;html=1;fillColor=none;"
            f"strokeColor={ann.color};strokeWidth=1.5;dashed=1;"
            f"verticalAlign=top;align=left;spacingTop=4;spacingLeft=8;"
            f"fontSize=11;fontStyle=2;"
        )
        shapes.append(
            Shape(
                id=f"__ann__{ann.label.replace(' ', '_')}",
                x=ann_x,
                y=ann_y,
                width=ann_r - ann_x,
                height=ann_b - ann_y,
                label=ann.label,
                style=ann_style,
            )
        )

    return BuildResult(
        title=d.title,
        shapes=shapes,
        connectors=connectors,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
    )
