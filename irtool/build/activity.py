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

    swimlane_h = _SWIMLANE_HEADER + _V_PAD + (max_level + 1) * (_NORMAL_H + _V_GAP)

    swimlane_by_id = {s.id: s for s in d.swimlanes}
    shapes: list[Shape] = []

    # Swimlanes left-to-right in declaration order.
    swimlane_x: dict[str, float] = {}
    for i, sw in enumerate(d.swimlanes):
        x = _MARGIN + i * (_SWIMLANE_W + _INTER_LANE_GAP)
        swimlane_x[sw.id] = x
        shapes.append(
            Shape(
                id=sw.id,
                x=x,
                y=_MARGIN,
                width=_SWIMLANE_W,
                height=swimlane_h,
                label=sw.name or sw.id,
                style=_SWIMLANE_STYLE,
            )
        )

    # Activities as children of their swimlane (relative coords).
    for a in d.activities:
        w, h = _NODE_DIM_BY_TYPE.get(a.type, (_NORMAL_W, _NORMAL_H))
        # Center horizontally within swimlane.
        rel_x = (_SWIMLANE_W - w) / 2
        # Row y = header + padding + level * (row_height). Row height stays
        # constant so activities align across lanes.
        row_top = _SWIMLANE_HEADER + _V_PAD + levels[a.id] * (_NORMAL_H + _V_GAP)
        # Vertically center the activity within its row.
        rel_y = row_top + (_NORMAL_H - h) / 2
        # Control nodes (start/end/merge/fork/join) are conventionally
        # unlabeled in UML — only show text for activities and decisions
        # where the label carries meaning. Allow override via explicit `name`.
        if a.type in ("start", "end", "merge", "fork", "join"):
            label = a.name if (a.name and a.name != a.id) else ""
        else:
            label = a.name or a.id
        shapes.append(
            Shape(
                id=a.id,
                x=rel_x,
                y=rel_y,
                width=w,
                height=h,
                label=label,
                style=_NODE_STYLE[a.type],
                parent=a.swimlane,
            )
        )

    # Connectors. Compute absolute positions so we can detect long edges
    # (≥2 levels apart OR skipping ≥1 lane) and route them via a gutter.
    activity_by_id = {a.id: a for a in d.activities}
    lane_idx = {sw.id: i for i, sw in enumerate(d.swimlanes)}
    abs_pos: dict[str, tuple[float, float, float, float]] = {}
    for a in d.activities:
        w, h = _NODE_DIM_BY_TYPE.get(a.type, (_NORMAL_W, _NORMAL_H))
        rel_x = (_SWIMLANE_W - w) / 2
        row_top = _SWIMLANE_HEADER + _V_PAD + levels[a.id] * (_NORMAL_H + _V_GAP)
        rel_y = row_top + (_NORMAL_H - h) / 2
        abs_pos[a.id] = (
            swimlane_x[a.swimlane] + rel_x,
            _MARGIN + rel_y,
            w,
            h,
        )

    rightmost = max(swimlane_x.values()) + _SWIMLANE_W
    leftmost = min(swimlane_x.values())
    right_gutter = rightmost + _GUTTER_PAD
    left_gutter = leftmost - _GUTTER_PAD
    abs_x = {sid: pos[0] for sid, pos in abs_pos.items()}

    # Inside the empty inset between a lane's boundary and its centered cells
    # (cells are 30px from a 240-wide lane's edges, so any x in the first/last
    # ~25px is collision-free). We pick a value safely inside that strip.
    _CHANNEL_INSET = 15

    def channel_for(src_lane_i: int, dst_lane_i: int) -> tuple[float, float]:
        """Return (channel_x, src_exit_x_track) for a cross-lane edge.

        Routes inside the empty left/right margin of the lane immediately
        adjacent to src in the direction of dst — i.e. visually distinct
        from the lane boundary stroke, but still in a cell-free strip.
        Falls back to the outer gutter for same-lane long edges.
        """
        if dst_lane_i > src_lane_i:
            # Right side of src: enter src's right neighbour at its left strip.
            next_lane = d.swimlanes[src_lane_i + 1].id
            return swimlane_x[next_lane] + _CHANNEL_INSET, 1.0
        if dst_lane_i < src_lane_i:
            # Left side of src: enter src's left neighbour at its right strip.
            prev_lane = d.swimlanes[src_lane_i - 1].id
            return swimlane_x[prev_lane] + _SWIMLANE_W - _CHANNEL_INSET, 0.0
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
                # Adjacent-level cross-lane edge — natural flow direction.
                # Exit src bottom (or top), cross the empty gap row between
                # BFS levels, enter dst top (or bottom). No side channel.
                exit_track = (0.5, 1.0) if dst_lvl >= src_lvl else (0.5, 0.0)
                track = (exit_track[0], exit_track[1], entry[0], entry[1])
                wp = [(src_cx, via_y), (dst_cx, via_y)]
            else:
                # Level-skipping edge — must dodge cells in intermediate rows.
                # Route through an empty channel in the adjacent lane's
                # margin, exiting src from the side facing the channel and
                # ENTERING DST FROM ITS SIDE (matching the channel side) so
                # this edge doesn't stack on top of any direct top-entry
                # arrow that another transition may use.
                channel_x, exit_x = channel_for(src_lane, dst_lane)
                dst_cy = ty + th / 2
                if channel_x <= tx:
                    side_entry = (0.0, 0.5)
                elif channel_x >= tx + tw:
                    side_entry = (1.0, 0.5)
                else:
                    side_entry = entry  # fallback (shouldn't normally hit)
                track = (exit_x, 0.5, side_entry[0], side_entry[1])
                wp = [
                    (channel_x, src_cy),
                    (channel_x, dst_cy),
                ]

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
