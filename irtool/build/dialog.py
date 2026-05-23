"""Dialog map: tree-style layout from BFS roots.

Each child is placed under its BFS parent. When a child is bidirectionally
paired with its parent, it gets placed directly under (same x), so the
two pair edges become parallel vertical lines — geometrically incapable
of crossing. Non-bidir children spread to the sides.

Long cross-level edges still route through an outside gutter.
"""

from __future__ import annotations

from collections import defaultdict, deque

from ..models import DialogDiagram
from ._common import (
    EDGE_STYLE,
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
    "rounded=1;arcSize=10;whiteSpace=wrap;html=1;fillColor=#d5e8d4;"
    "strokeColor=#82b366;fontSize=13;"
)
_W, _H = 200, 80
_H_GAP, _V_GAP = 80, 130
_MARGIN = 80
_LONG_EDGE_LEVELS = 2
_GUTTER_PAD = 60


def _bfs(d: DialogDiagram) -> tuple[dict[str, int], dict[str, str | None]]:
    """Return (level_by_id, parent_by_id) using BFS from initial-flagged
    or zero-in-degree nodes."""
    incoming: dict[str, int] = defaultdict(int)
    adj: dict[str, list[str]] = defaultdict(list)
    for t in d.transitions:
        incoming[t.dst] += 1
        adj[t.src].append(t.dst)

    ids = [x.id for x in d.dialogs]
    flagged = [x.id for x in d.dialogs if x.is_initial]
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


def _spine(d: DialogDiagram) -> set[str]:
    """Identify the diagram's main-flow spine: the shortest path from any
    is_initial dialog to any is_final dialog. Returns the set of dialog
    ids on that path. Empty if no spine can be determined."""
    initials = [x.id for x in d.dialogs if x.is_initial]
    finals = {x.id for x in d.dialogs if x.is_final}
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
    """Y-level for each cell, in 'spine progression' units.

    Bidir-paired children share their parent's level (they're a side-step,
    not a forward step). Everything else gets parent + 1.
    """
    # BFS order so parents resolve before children.
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
    # Unreached cells (validator should catch but be safe)
    for did in parent:
        levels.setdefault(did, max(levels.values(), default=0) + 1)
    return levels


def _layout(d: DialogDiagram) -> dict[str, tuple[float, float]]:
    """Tree layout, spine-aware.

    Each child placed under its parent. Among siblings, priority order is:
      1. Spine child (lies on the main is_initial -> is_final path)
      2. Bidir child (loops back to parent; a side trip)
      3. Other one-way child (exception)
    The top-priority child sits directly under the parent. Others fan
    out to alternating sides.

    Y position uses spine_levels (bidir = same level as parent), so
    bidir loops render as same-row neighbours rather than as descendants.
    """
    _, parent = _bfs(d)
    bidir = find_bidirectional(d.transitions)
    spine = _spine(d)
    roots = [x.id for x in d.dialogs if parent[x.id] is None]
    spine_levels = _spine_levels(parent, bidir, roots)

    children: dict[str | None, list[str]] = defaultdict(list)
    decl = {x.id: i for i, x in enumerate(d.dialogs)}
    for did, p in parent.items():
        children[p].append(did)

    def is_bidir_with_parent(c: str) -> bool:
        p = parent[c]
        return p is not None and ((p, c) in bidir or (c, p) in bidir)

    def child_rank(c: str) -> int:
        # 0 = spine, 1 = bidir loop, 2 = one-way exception
        if c in spine and parent[c] in spine:
            return 0
        if is_bidir_with_parent(c):
            return 1
        return 2

    for p in children:
        children[p].sort(key=lambda c: (child_rank(c), decl[c]))

    # Compute subtree width in "slot units" (1 slot = _W + _H_GAP).
    width_cache: dict[str, int] = {}

    def width(did: str) -> int:
        if did in width_cache:
            return width_cache[did]
        cs = children.get(did, [])
        if not cs:
            width_cache[did] = 1
            return 1
        if len(cs) == 1:
            width_cache[did] = width(cs[0])
            return width_cache[did]
        # First child is highest-priority (spine or bidir). If its rank
        # is < 2 it gets the centered slot under self.
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
        width_cache[did] = max(1, left_w + center_w + right_w)
        return width_cache[did]

    positions: dict[str, tuple[float, float]] = {}

    def place(did: str, x_center: float) -> None:
        y = _MARGIN + spine_levels[did] * (_H + _V_GAP)
        positions[did] = (x_center, y)
        cs = children.get(did, [])
        if not cs:
            return
        if len(cs) == 1:
            only = cs[0]
            # Single child at same spine level (bidir loop) needs to be
            # offset on x, otherwise it overlaps the parent.
            if spine_levels[only] == spine_levels[did]:
                place(only, x_center + _W + _H_GAP)
            else:
                place(only, x_center)
            return

        first = cs[0]
        if child_rank(first) < 2:
            # Spine or bidir child sits directly under parent in x.
            # (Spine goes to next y via spine_levels; bidir stays at same y.)
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

    # Place each root tree side-by-side.
    cur_x = _MARGIN + _W / 2
    slot = _W + _H_GAP
    for r in children[None]:
        w = width(r)
        # Center root over its subtree
        place(r, cur_x + (w - 1) * slot / 2)
        cur_x += w * slot

    return positions


def build(d: DialogDiagram) -> BuildResult:
    positions = _layout(d)
    by_id = {x.id: x for x in d.dialogs}

    shapes: list[Shape] = []
    for did, (x, y) in positions.items():
        shapes.append(
            Shape(
                id=did,
                x=x - _W / 2,  # positions store CENTER x; Shape uses top-left
                y=y,
                width=_W,
                height=_H,
                label=by_id[did].name or did,
                style=_STYLE,
            )
        )

    # Recompute top-left positions for downstream use.
    tl_pos = {did: (x - _W / 2, y) for did, (x, y) in positions.items()}

    # Use spine_levels (which collapses bidir-loops to parent's level) for
    # long-edge detection. Otherwise a bidir partner would look "1 level
    # away" via BFS but in fact be at the same flow position.
    _, parent_map = _bfs(d)
    bidir_set_tmp = find_bidirectional(d.transitions)
    roots_tmp = [x.id for x in d.dialogs if parent_map[x.id] is None]
    levels = _spine_levels(parent_map, bidir_set_tmp, roots_tmp)

    min_x = min(p[0] for p in tl_pos.values())
    max_x = max(p[0] for p in tl_pos.values()) + _W
    left_gutter = min_x - _GUTTER_PAD
    right_gutter = max_x + _GUTTER_PAD
    canvas_mid_x = (min_x + max_x) / 2

    bidir = find_bidirectional(d.transitions)
    connectors = []
    for idx, t in enumerate(d.transitions):
        if t.src == t.dst:
            sx, sy = tl_pos[t.src]
            arc_y = sy - 35
            c = make_connector(idx, t.src, t.dst, t.trigger or "",
                               EDGE_STYLE, (0.7, 0.0, 0.9, 0.0))
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
            c = make_connector(idx, t.src, t.dst, t.trigger or "",
                               EDGE_STYLE, track)
            c.waypoints = wp
            connectors.append(c)
            continue

        track = None
        label_off = (0.0, 0.0)
        if (t.src, t.dst) in bidir:
            track = parallel_track(t.src, t.dst, sx, tx, sy, ty)
            label_off = parallel_label_offset(t.src, t.dst, sx, tx, sy, ty)
        c = make_connector(idx, t.src, t.dst, t.trigger or "", EDGE_STYLE, track)
        c.label_offset_x, c.label_offset_y = label_off
        connectors.append(c)

    # Pseudo-states.
    for dialog in d.dialogs:
        x, y = tl_pos[dialog.id]
        if dialog.is_initial:
            sh, conn = initial_pseudo(dialog.id, x, y, _W)
            shapes.append(sh)
            connectors.append(conn)
        if dialog.is_final:
            sh, conn = final_pseudo(dialog.id, x, y, _W, _H, label="Exit")
            shapes.append(sh)
            connectors.append(conn)

    # Composite parents: wrap children in container cells if the IR
    # declares any nested dialogs via `parent:`.
    parent_of = {x.id: x.parent for x in d.dialogs}
    shapes = apply_composites(shapes, parent_of)

    # Compute canvas using only top-level (parent=="1") shapes so the
    # nested children don't double-count.
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
