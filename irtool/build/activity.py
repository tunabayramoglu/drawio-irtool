"""Activity diagram: vertical swimlanes (columns), BFS-levelled activities.

Each swimlane is a container shape. Activities live as children of their
swimlane and have coordinates relative to it. Transitions are normal edges
with parent='1' that reference activity cells regardless of swimlane.
"""

from __future__ import annotations

from collections import defaultdict, deque

from ..models import ActivityDiagram, ActivityType
from ._common import (
    EDGE_STYLE,
    find_bidirectional,
    make_connector,
    outside_route,
    parallel_track,
)
from .types import BuildResult, Shape


_SWIMLANE_W = 240
_SWIMLANE_HEADER = 30
_V_PAD = 30
_V_GAP = 50
_MARGIN = 40
_INTER_LANE_GAP = 0  # touch each other; the stroke separates them
_LONG_EDGE_LEVELS = 2
_LONG_LANE_SPAN = 2
_GUTTER_PAD = 40


_NORMAL_W, _NORMAL_H = 180, 70
# Horizontal gap between sibling columns when same-level nodes in the same
# swimlane are spread side-by-side. Sized so edges from a shared source to
# different siblings get naturally distinct orthogonal paths.
_SIBLING_H_GAP = 40
# Inner margin on each side of a swimlane (the strip between the lane
# boundary stroke and the outermost sibling column).
_LANE_MARGIN = 30
_NODE_DIM_BY_TYPE: dict[ActivityType, tuple[int, int]] = {
    "start": (40, 40),
    "end": (40, 40),
    "normal": (_NORMAL_W, _NORMAL_H),
    "decision": (90, 90),
    "merge": (90, 90),
    "fork": (180, 12),
    "join": (180, 12),
}


_NODE_STYLE: dict[ActivityType, str] = {
    # Match dialog/state pseudo-state styling so all three UML diagram
    # families render their entry/exit markers identically: filled black
    # dot for entry, bullseye (shape=endState) for exit.
    "start": "ellipse;fillColor=#000000;strokeColor=#000000;html=1;",
    "end": (
        "ellipse;shape=endState;fillColor=#000000;strokeColor=#000000;"
        "perimeter=ellipsePerimeter;html=1;"
    ),
    "normal": (
        "rounded=1;arcSize=40;whiteSpace=wrap;html=1;fillColor=#fff2cc;"
        "strokeColor=#d6b656;fontSize=13;"
    ),
    "decision": (
        "rhombus;whiteSpace=wrap;html=1;fillColor=#ffe6cc;"
        "strokeColor=#d79b00;fontSize=12;"
    ),
    "merge": (
        "rhombus;whiteSpace=wrap;html=1;fillColor=#ffe6cc;"
        "strokeColor=#d79b00;fontSize=12;"
    ),
    "fork": "rounded=0;fillColor=#000000;strokeColor=#000000;html=1;",
    "join": "rounded=0;fillColor=#000000;strokeColor=#000000;html=1;",
}


_SWIMLANE_STYLE = (
    "shape=swimlane;html=1;startSize={hdr};horizontal=1;"
    "fillColor=#f5f5f5;strokeColor=#666666;fontSize=14;fontStyle=1;"
    "verticalAlign=top;align=center;swimlaneFillColor=#ffffff;"
).format(hdr=_SWIMLANE_HEADER)


def _assign_levels(d: ActivityDiagram) -> dict[str, int]:
    """Longest-path layering via Kahn's topo sort.

    Convergence nodes (merges, ends) sit at level = max(level(pred)) + 1,
    so all incoming edges point forward instead of backward across the
    diagram. Cycles fall back to BFS-from-start.
    """
    ids = {a.id for a in d.activities}
    adj: dict[str, list[str]] = defaultdict(list)
    rev: dict[str, list[str]] = defaultdict(list)
    in_deg: dict[str, int] = {a.id: 0 for a in d.activities}
    for t in d.transitions:
        if t.src in ids and t.dst in ids:
            adj[t.src].append(t.dst)
            rev[t.dst].append(t.src)
            in_deg[t.dst] += 1

    level: dict[str, int] = {}
    q: deque[str] = deque(a.id for a in d.activities if in_deg[a.id] == 0)
    while q:
        node = q.popleft()
        preds = rev.get(node, [])
        level[node] = max((level[p] for p in preds if p in level), default=-1) + 1
        for nxt in adj.get(node, []):
            in_deg[nxt] -= 1
            if in_deg[nxt] == 0:
                q.append(nxt)

    # Cyclic remnants — BFS from start as fallback.
    if len(level) < len(d.activities):
        start = next((a for a in d.activities if a.type == "start"),
                     d.activities[0])
        level.setdefault(start.id, 0)
        bq: deque[str] = deque([start.id])
        while bq:
            node = bq.popleft()
            for nxt in adj.get(node, []):
                if nxt not in level:
                    level[nxt] = level[node] + 1
                    bq.append(nxt)
        fallback = max(level.values(), default=0) + 1
        for a in d.activities:
            level.setdefault(a.id, fallback)
    return level


def build(d: ActivityDiagram) -> BuildResult:
    levels = _assign_levels(d)
    max_level = max(levels.values(), default=0)

    # Group activities by (swimlane, level). Siblings at the same BFS depth
    # within the same lane are spread HORIZONTALLY (side-by-side columns)
    # so that fan-out edges from a shared source (e.g. decision) get
    # naturally distinct orthogonal paths to each target.
    lane_groups: dict[tuple[str, int], list[str]] = defaultdict(list)
    for a in d.activities:
        lane_groups[(a.swimlane, levels[a.id])].append(a.id)

    decl_idx = {a.id: i for i, a in enumerate(d.activities)}

    # Column index for each activity within its (swimlane, level) group.
    col: dict[str, int] = {}
    # Per-swimlane: max columns in any one BFS level → drives lane width.
    max_cols: dict[str, int] = defaultdict(int)
    for (lane_id, _lvl), members in lane_groups.items():
        for ci, aid in enumerate(sorted(members, key=lambda m: decl_idx[m])):
            col[aid] = ci
        max_cols[lane_id] = max(max_cols[lane_id], len(members))

    # Swimlane width = widest node in a column * columns + gaps + margins.
    lane_width: dict[str, float] = {}
    for sw in d.swimlanes:
        n = max_cols.get(sw.id, 1)
        # Each column must fit the widest node that could appear (decision
        # rhombus = 90, normal rounded rect = 180, fork/join bar = 180).
        col_w = _NORMAL_W + _SIBLING_H_GAP
        lane_width[sw.id] = max(_SWIMLANE_W, 2 * _LANE_MARGIN + n * col_w - _SIBLING_H_GAP)

    # Uniform row height — all levels use the same vertical spacing so
    # activities align across lanes.
    _ROW_H = _NORMAL_H + _V_GAP
    swimlane_h = _SWIMLANE_HEADER + _V_PAD + (max_level + 1) * _ROW_H

    swimlane_by_id = {s.id: s for s in d.swimlanes}
    shapes: list[Shape] = []

    # Swimlanes left-to-right in declaration order, each with its computed
    # width.
    swimlane_x: dict[str, float] = {}
    cur_x = _MARGIN
    for sw in d.swimlanes:
        w = lane_width[sw.id]
        swimlane_x[sw.id] = cur_x
        shapes.append(
            Shape(
                id=sw.id,
                x=cur_x,
                y=_MARGIN,
                width=w,
                height=swimlane_h,
                label=sw.name or sw.id,
                style=_SWIMLANE_STYLE,
            )
        )
        cur_x += w + _INTER_LANE_GAP

    # Place activities as children of their swimlane. All siblings in the
    # same (swimlane, level) group share the same Y but get distinct X
    # columns so they sit side-by-side.
    for a in d.activities:
        act_w, act_h = _NODE_DIM_BY_TYPE.get(a.type, (_NORMAL_W, _NORMAL_H))
        lw = lane_width[a.swimlane]
        n_cols_siblings = max_cols.get(a.swimlane, 1)
        total_cols_w = n_cols_siblings * (_NORMAL_W + _SIBLING_H_GAP) - _SIBLING_H_GAP
        start_x = (lw - total_cols_w) / 2
        ci = col[a.id]
        col_cx = start_x + ci * (_NORMAL_W + _SIBLING_H_GAP) + _NORMAL_W / 2
        rel_x = col_cx - act_w / 2
        # Vertical: all siblings at this level share the same row.
        row_top = _SWIMLANE_HEADER + _V_PAD + levels[a.id] * _ROW_H
        rel_y = row_top + (_NORMAL_H - act_h) / 2
        if a.type in ("start", "end", "merge", "fork", "join"):
            label = a.name if (a.name and a.name != a.id) else ""
        else:
            label = a.name or a.id
        shapes.append(
            Shape(
                id=a.id,
                x=rel_x,
                y=rel_y,
                width=act_w,
                height=act_h,
                label=label,
                style=_NODE_STYLE[a.type],
                parent=a.swimlane,
            )
        )

    # Absolute positions for edge routing.
    activity_by_id = {a.id: a for a in d.activities}
    lane_idx = {sw.id: i for i, sw in enumerate(d.swimlanes)}
    abs_pos: dict[str, tuple[float, float, float, float]] = {}
    for a in d.activities:
        act_w, act_h = _NODE_DIM_BY_TYPE.get(a.type, (_NORMAL_W, _NORMAL_H))
        lw = lane_width[a.swimlane]
        n_cols_siblings = max_cols.get(a.swimlane, 1)
        total_cols_w = n_cols_siblings * (_NORMAL_W + _SIBLING_H_GAP) - _SIBLING_H_GAP
        start_x = (lw - total_cols_w) / 2
        ci = col[a.id]
        col_cx = start_x + ci * (_NORMAL_W + _SIBLING_H_GAP) + _NORMAL_W / 2
        rel_x = col_cx - act_w / 2
        row_top = _SWIMLANE_HEADER + _V_PAD + levels[a.id] * _ROW_H
        rel_y = row_top + (_NORMAL_H - act_h) / 2
        abs_pos[a.id] = (
            swimlane_x[a.swimlane] + rel_x,
            _MARGIN + rel_y,
            act_w,
            act_h,
        )

    rightmost = max(swimlane_x[lid] + lane_width[lid] for lid in lane_width)
    leftmost = min(swimlane_x.values())
    right_gutter = rightmost + _GUTTER_PAD
    left_gutter = leftmost - _GUTTER_PAD
    abs_x = {sid: pos[0] for sid, pos in abs_pos.items()}

    _CHANNEL_INSET = 15

    def channel_for(src_lane_i: int, dst_lane_i: int) -> tuple[float, float]:
        if dst_lane_i > src_lane_i:
            next_lane = d.swimlanes[src_lane_i + 1].id
            return swimlane_x[next_lane] + _CHANNEL_INSET, 1.0
        if dst_lane_i < src_lane_i:
            prev_lane = d.swimlanes[src_lane_i - 1].id
            return swimlane_x[prev_lane] + lane_width[prev_lane] - _CHANNEL_INSET, 0.0
        return right_gutter, 1.0

    bidir = find_bidirectional(d.transitions)

    def _edge_label(t: ActivityTransition) -> str:
        text = t.label
        if t.guard:
            text = f"{text} [{t.guard}]" if text else f"[{t.guard}]"
        return text

    connectors = []
    for idx, t in enumerate(d.transitions):
        src_lvl = levels[t.src]
        dst_lvl = levels[t.dst]
        src_lane = lane_idx[activity_by_id[t.src].swimlane]
        dst_lane = lane_idx[activity_by_id[t.dst].swimlane]
        level_span = abs(dst_lvl - src_lvl)
        lane_span = abs(dst_lane - src_lane)

        is_long = (
            level_span >= _LONG_EDGE_LEVELS
            or (lane_span >= _LONG_LANE_SPAN and level_span >= 1)
        )

        if is_long and t.src != t.dst:
            sx, sy, sw, sh = abs_pos[t.src]
            tx, ty, tw, th = abs_pos[t.dst]
            src_cx = sx + sw / 2
            src_cy = sy + sh / 2
            dst_cx = tx + tw / 2
            if dst_lvl >= src_lvl:
                via_y = ty - _V_GAP / 2
                entry = (0.5, 0.0)
            else:
                via_y = ty + th + _V_GAP / 2
                entry = (0.5, 1.0)

            if level_span <= 1:
                exit_track = (0.5, 1.0) if dst_lvl >= src_lvl else (0.5, 0.0)
                track = (exit_track[0], exit_track[1], entry[0], entry[1])
                wp = [(src_cx, via_y), (dst_cx, via_y)]
            else:
                channel_x, exit_x = channel_for(src_lane, dst_lane)
                dst_cy = ty + th / 2
                if channel_x <= tx:
                    side_entry = (0.0, 0.5)
                elif channel_x >= tx + tw:
                    side_entry = (1.0, 0.5)
                else:
                    side_entry = entry
                track = (exit_x, 0.5, side_entry[0], side_entry[1])
                wp = [(channel_x, src_cy), (channel_x, dst_cy)]

            c = make_connector(idx, t.src, t.dst, _edge_label(t), EDGE_STYLE, track)
            c.waypoints = wp
            connectors.append(c)
            continue

        track = None
        if (t.src, t.dst) in bidir:
            track = parallel_track(t.src, t.dst, abs_x[t.src], abs_x[t.dst])
        connectors.append(make_connector(idx, t.src, t.dst, _edge_label(t), EDGE_STYLE, track))

    canvas_w = int(rightmost + _GUTTER_PAD + _MARGIN)
    canvas_h = _MARGIN + swimlane_h + _MARGIN
    return BuildResult(
        title=d.title,
        shapes=shapes,
        connectors=connectors,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
    )
