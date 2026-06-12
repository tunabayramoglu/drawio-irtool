"""State diagram: spine-aware tree layout (ported from dialog.py).

Each child is placed under its BFS parent. The shortest path from an
is_initial state to an is_final state defines the main vertical spine.
Bidir-paired children sit at the parent's y level (a side-step rather
than a forward step); other one-way exceptions branch sideways.

Falls back to a plain layered tree when no initial/final flags pin a
spine.
"""

from __future__ import annotations

from collections import defaultdict, deque

from ..models import StateDiagram
from ._common import (
    EDGE_STYLE,
    STRAIGHT_EDGE_STYLE,
    apply_composites,
    final_pseudo,
    find_bidirectional,
    initial_pseudo,
    make_connector,
    outside_route,
    parallel_label_offset,
    parallel_track,
)
from .types import BuildResult, Shape


_STYLE = (
    "rounded=1;arcSize=40;whiteSpace=wrap;html=1;"
    "fillColor=#dae8fc;strokeColor=#6c8ebf;fontSize=13;"
)
_W, _H = 160, 70
_H_GAP, _V_GAP = 80, 130
_MARGIN = 80
_LONG_EDGE_LEVELS = 2
_GUTTER_PAD = 60


def _format_transition(label_parts: tuple[str, str, str]) -> str:
    event, guard, action = label_parts
    text = event
    if guard:
        text = f"{text} [{guard}]"
    if action:
        text = f"{text} / {action}"
    return text


def _bfs(d: StateDiagram) -> tuple[dict[str, int], dict[str, str | None]]:
    incoming: dict[str, int] = defaultdict(int)
    adj: dict[str, list[str]] = defaultdict(list)
    for t in d.transitions:
        incoming[t.dst] += 1
        adj[t.src].append(t.dst)

    ids = [s.id for s in d.states]
    flagged = [s.id for s in d.states if s.is_initial]
    if flagged:
        roots = flagged
    else:
        roots = [i for i in ids if incoming[i] == 0] or [sorted(ids)[0]]

    level: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    q: deque[str] = deque()
    for r in roots:
        level[r] = 0
        parent[r] = None
        q.append(r)
    while q:
        node = q.popleft()
        for nxt in adj.get(node, []):
            if nxt not in level:
                level[nxt] = level[node] + 1
                parent[nxt] = node
                q.append(nxt)
    for i in ids:
        if i not in level:
            level[i] = max(level.values(), default=0) + 1
            parent[i] = None
    return level, parent


def _spine(d: StateDiagram) -> set[str]:
    initials = [s.id for s in d.states if s.is_initial]
    finals = {s.id for s in d.states if s.is_final}
    if not initials or not finals:
        return set()

    adj: dict[str, list[str]] = defaultdict(list)
    for t in d.transitions:
        adj[t.src].append(t.dst)

    initial = initials[0]
    p: dict[str, str | None] = {initial: None}
    q: deque[str] = deque([initial])
    target: str | None = None
    while q:
        node = q.popleft()
        if node in finals:
            target = node
            break
        for nxt in adj.get(node, []):
            if nxt not in p:
                p[nxt] = node
                q.append(nxt)

    if target is None:
        return set()

    path: set[str] = set()
    cur: str | None = target
    while cur is not None:
        path.add(cur)
        cur = p[cur]
    return path


def _spine_levels(
    parent: dict[str, str | None],
    bidir: set[tuple[str, str]],
    roots: list[str],
) -> dict[str, int]:
    children_of: dict[str | None, list[str]] = defaultdict(list)
    for c, p in parent.items():
        children_of[p].append(c)

    levels: dict[str, int] = {r: 0 for r in roots}
    q: deque[str] = deque(roots)
    while q:
        node = q.popleft()
        for c in children_of.get(node, []):
            if c not in levels:
                is_bidir_pair = (node, c) in bidir or (c, node) in bidir
                levels[c] = levels[node] if is_bidir_pair else levels[node] + 1
                q.append(c)
    for sid in parent:
        levels.setdefault(sid, max(levels.values(), default=0) + 1)
    return levels


def _layout(d: StateDiagram) -> tuple[
    dict[str, tuple[float, float]], dict[str, int]
]:
    _, parent = _bfs(d)
    bidir = find_bidirectional(d.transitions)
    spine = _spine(d)
    roots = [s.id for s in d.states if parent[s.id] is None]
    spine_levels = _spine_levels(parent, bidir, roots)

    children: dict[str | None, list[str]] = defaultdict(list)
    decl = {s.id: i for i, s in enumerate(d.states)}
    for sid, p in parent.items():
        children[p].append(sid)

    def is_bidir_with_parent(c: str) -> bool:
        p = parent[c]
        return p is not None and ((p, c) in bidir or (c, p) in bidir)

    def child_rank(c: str) -> int:
        if c in spine and parent[c] in spine:
            return 0
        if is_bidir_with_parent(c):
            return 1
        return 2

    for p in children:
        children[p].sort(key=lambda c: (child_rank(c), decl[c]))

    width_cache: dict[str, int] = {}

    def width(sid: str) -> int:
        if sid in width_cache:
            return width_cache[sid]
        cs = children.get(sid, [])
        if not cs:
            width_cache[sid] = 1
            return 1
        if len(cs) == 1:
            width_cache[sid] = width(cs[0])
            return width_cache[sid]
        first = cs[0]
        if child_rank(first) < 2:
            center_w = width(first)
            sides = cs[1:]
        else:
            center_w = 1
            sides = cs
        n_right = (len(sides) + 1) // 2
        n_left = len(sides) // 2
        right_w = sum(width(c) for c in sides[:n_right])
        left_w = sum(width(c) for c in sides[n_right:n_right + n_left])
        width_cache[sid] = max(1, left_w + center_w + right_w)
        return width_cache[sid]

    positions: dict[str, tuple[float, float]] = {}

    def place(sid: str, x_center: float) -> None:
        y = _MARGIN + spine_levels[sid] * (_H + _V_GAP)
        positions[sid] = (x_center, y)
        cs = children.get(sid, [])
        if not cs:
            return
        if len(cs) == 1:
            only = cs[0]
            if spine_levels[only] == spine_levels[sid]:
                place(only, x_center + _W + _H_GAP)
            else:
                place(only, x_center)
            return

        first = cs[0]
        if child_rank(first) < 2:
            place(first, x_center)
            sides = cs[1:]
        else:
            sides = cs

        slot = _W + _H_GAP
        n_right = (len(sides) + 1) // 2
        right = sides[:n_right]
        left = sides[n_right:]

        cur = x_center + slot
        for c in right:
            w = width(c)
            place(c, cur + (w - 1) * slot / 2)
            cur += w * slot

        cur = x_center - slot
        for c in left:
            w = width(c)
            place(c, cur - (w - 1) * slot / 2)
            cur -= w * slot

    cur_x = _MARGIN + _W / 2
    slot = _W + _H_GAP
    for r in children[None]:
        w = width(r)
        place(r, cur_x + (w - 1) * slot / 2)
        cur_x += w * slot

    return positions, spine_levels


def build(d: StateDiagram) -> BuildResult:
    center_pos, levels = _layout(d)
    # Positions store CENTER x; convert to top-left for Shape and routing.
    tl_pos = {sid: (cx - _W / 2, y) for sid, (cx, y) in center_pos.items()}

    state_by_id = {s.id: s for s in d.states}
    shapes: list[Shape] = []
    for sid, (x, y) in tl_pos.items():
        s = state_by_id[sid]
        if s.is_history:
            # History pseudo-state: small white circle with "H" (shallow)
            # or "H*" (deep). Center it on the slot the layout reserved.
            label = "H*" if s.history_deep else "H"
            size = 32
            shapes.append(
                Shape(
                    id=sid,
                    x=x + (_W - size) / 2,
                    y=y + (_H - size) / 2,
                    width=size,
                    height=size,
                    label=label,
                    style=(
                        "ellipse;whiteSpace=wrap;html=1;fillColor=#FFFFFF;"
                        "strokeColor=#000000;fontSize=14;fontStyle=1;"
                        "align=center;verticalAlign=middle;"
                    ),
                )
            )
        else:
            label = s.name or sid
            if s.entry_action or s.exit_action:
                parts = [f"<b>{label}</b>"]
                if s.entry_action:
                    parts.append(
                        f"<span style='font-size:10px;color:#555'>"
                        f"entry / {s.entry_action}</span>"
                    )
                if s.exit_action:
                    parts.append(
                        f"<span style='font-size:10px;color:#555'>"
                        f"exit / {s.exit_action}</span>"
                    )
                label = "<br>".join(parts)
            shapes.append(
                Shape(
                    id=sid,
                    x=x,
                    y=y,
                    width=_W,
                    height=_H,
                    label=label,
                    style=_STYLE,
                )
            )

    min_x = min(p[0] for p in tl_pos.values())
    max_x = max(p[0] for p in tl_pos.values()) + _W
    left_gutter = min_x - _GUTTER_PAD
    right_gutter = max_x + _GUTTER_PAD
    canvas_mid_x = (min_x + max_x) / 2

    bidir = find_bidirectional(d.transitions)
    connectors = []
    for idx, t in enumerate(d.transitions):
        label = _format_transition((t.event, t.guard, t.action))
        if t.src == t.dst:
            sx, sy = tl_pos[t.src]
            arc_y = sy - 35
            c = make_connector(idx, t.src, t.dst, label, EDGE_STYLE,
                               (0.7, 0.0, 0.9, 0.0))
            c.waypoints = [(sx + _W * 0.7, arc_y), (sx + _W * 0.9, arc_y)]
            connectors.append(c)
            continue

        src_lvl = levels[t.src]
        dst_lvl = levels[t.dst]
        sx, sy = tl_pos[t.src]
        tx, ty = tl_pos[t.dst]

        if abs(dst_lvl - src_lvl) >= _LONG_EDGE_LEVELS:
            mid_x = (sx + tx) / 2 + _W / 2
            gutter = left_gutter if mid_x < canvas_mid_x else right_gutter
            track, wp = outside_route(
                (sx, sy), (_W, _H), (tx, ty), (_W, _H), gutter
            )
            c = make_connector(idx, t.src, t.dst, label, EDGE_STYLE, track)
            c.waypoints = wp
            connectors.append(c)
            continue

        track = None
        label_off = (0.0, 0.0)
        style = EDGE_STYLE
        if (t.src, t.dst) in bidir:
            track = parallel_track(t.src, t.dst, sx, tx, sy, ty)
            label_off = parallel_label_offset(t.src, t.dst, sx, tx, sy, ty)
            if abs(tx - sx) > 30 and abs(ty - sy) > abs(tx - sx) * 0.5:
                style = STRAIGHT_EDGE_STYLE
        c = make_connector(idx, t.src, t.dst, label, style, track)
        c.label_offset_x, c.label_offset_y = label_off
        connectors.append(c)

    for s in d.states:
        x, y = tl_pos[s.id]
        if s.is_initial:
            sh, conn = initial_pseudo(s.id, x, y, _W)
            shapes.append(sh)
            connectors.append(conn)
        if s.is_final:
            sh, conn = final_pseudo(s.id, x, y, _W, _H, label="Exit")
            shapes.append(sh)
            connectors.append(conn)

    parent_of = {s.id: s.parent for s in d.states}
    shapes = apply_composites(shapes, parent_of)

    top_level = [s for s in shapes if s.parent == "1"]
    canvas_w = int(max(s.x + s.width for s in top_level) + _MARGIN + _GUTTER_PAD)
    canvas_h = int(max(s.y + s.height for s in top_level) + _MARGIN)
    return BuildResult(
        title=d.title,
        shapes=shapes,
        connectors=connectors,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
    )
