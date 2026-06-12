"""Class diagram: inheritance-aware tree layout.

Inheritance relationships (child→parent) drive the vertical hierarchy.
Each inheritance tree is laid out as a sub-tree with the root centered
over its children's combined width. Classes that don't participate in
any inheritance go into a separate "free" row above the trees, so the
common case (a hierarchy + a handful of unrelated supporting classes)
reads top-to-bottom without crossing.

Non-inheritance relationships (association, composition, etc.) do not
drive layout — they're rendered as edges over whatever positions the
inheritance layout produced.
"""

from __future__ import annotations

from collections import defaultdict

from ..models import ClassDef, ClassDiagram
from ._common import EDGE_STYLE, make_connector
from .types import BuildResult, Shape


_W = 240
_ROW_HEIGHT = 18
_HEADER_HEIGHT = 36
_SECTION_PAD = 10
_MIN_H = 80
# Gap between cells. Sized so the edge between any two adjacent cells
# is longer than typical relationship labels ("contains 1..*", "refers
# to 1", etc. — up to ~80px at the default 12pt font). A label drawn at
# the edge midpoint then never reaches into either cell's border.
_H_GAP = 120
_V_GAP = 110
_MARGIN = 60


def _measure(c: ClassDef) -> int:
    attrs = len(c.attributes)
    methods = len(c.methods)
    h = _HEADER_HEIGHT + _SECTION_PAD
    if c.is_interface:
        h += _ROW_HEIGHT  # stereotype line above the name
    if attrs:
        h += attrs * _ROW_HEIGHT + _SECTION_PAD
    if methods:
        h += methods * _ROW_HEIGHT + _SECTION_PAD
    return max(_MIN_H, h)


# Visibility prefix → rendered marker. Strings with one of these leading
# characters get the prefix stripped and replaced with a colored span so
# the UML symbol is preserved but visually distinct from the member name.
_VISIBILITY_MARKERS = {
    "+": ("+", "#2e7d32"),   # public — green
    "-": ("-", "#c62828"),   # private — red
    "#": ("#", "#f57c00"),   # protected — orange
    "~": ("~", "#6a1b9a"),   # package — purple
}


def _format_member(text: str) -> str:
    """Render a member line. If it starts with a UML visibility marker
    (+ - # ~), color the marker; otherwise render as-is. Whitespace
    between the marker and the rest is normalized to a single space."""
    if not text:
        return ""
    head = text[0]
    if head in _VISIBILITY_MARKERS:
        sym, color = _VISIBILITY_MARKERS[head]
        rest = text[1:].lstrip()
        return (
            f"<span style='color:{color};font-weight:bold'>{sym}</span> {rest}"
        )
    return text


def _format_label(c: ClassDef) -> str:
    parts = []
    stereo = c.stereotype or ("interface" if c.is_interface else "")
    if stereo:
        parts.append(
            f"<span style='font-size:11px;color:#666'>&laquo;{stereo}&raquo;</span>"
        )
    head = c.name or c.id
    if c.is_abstract or c.is_interface:
        head = f"<i>{head}</i>"
    parts.append(f"<b>{head}</b>")
    if c.attributes:
        parts.append("<hr style='margin:2px 0'>")
        parts.extend(_format_member(a) for a in c.attributes)
    if c.methods:
        parts.append("<hr style='margin:2px 0'>")
        parts.extend(_format_member(m) for m in c.methods)
    return "<br>".join(parts)


_BOX_STYLE = (
    "rounded=0;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;"
    "fontSize=12;align=left;verticalAlign=top;spacingLeft=10;spacingTop=6;"
    "spacingBottom=6;"
)


_REL_END_ARROW = {
    "inheritance": "endArrow=block;endFill=0;",
    "realization": "endArrow=block;endFill=0;dashed=1;",
    "composition": "endArrow=none;startArrow=diamondThin;startFill=1;startSize=14;",
    "aggregation": "endArrow=none;startArrow=diamondThin;startFill=0;startSize=14;",
    "association": "endArrow=open;",
    "dependency": "endArrow=open;dashed=1;",
}


# Relationship types that drive vertical hierarchy. Both inheritance
# (class-to-class) and realization (class-implements-interface) put the
# child below the parent in standard UML notation, so they layout the
# same way.
_HIERARCHY_TYPES = {"inheritance", "realization"}


def _inheritance_graph(
    d: ClassDiagram,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    parents: dict[str, list[str]] = defaultdict(list)
    children: dict[str, list[str]] = defaultdict(list)
    for r in d.relationships:
        if r.type in _HIERARCHY_TYPES:
            parents[r.src].append(r.dst)
            children[r.dst].append(r.src)
    return parents, children


def _inheritance_components(
    d: ClassDiagram,
    parents: dict[str, list[str]],
    children: dict[str, list[str]],
) -> list[set[str]]:
    involved: set[str] = set()
    for r in d.relationships:
        if r.type in _HIERARCHY_TYPES:
            involved.add(r.src)
            involved.add(r.dst)

    visited: set[str] = set()
    components: list[set[str]] = []
    for c in d.classes:
        if c.id not in involved or c.id in visited:
            continue
        comp: set[str] = set()
        stack = [c.id]
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            comp.add(n)
            for nb in parents.get(n, []) + children.get(n, []):
                if nb not in visited:
                    stack.append(nb)
        components.append(comp)
    return components


def build(d: ClassDiagram) -> BuildResult:
    heights = {c.id: _measure(c) for c in d.classes}
    parents, children = _inheritance_graph(d)
    components = _inheritance_components(d, parents, children)

    in_any_tree = set().union(*components) if components else set()
    free_classes = [c for c in d.classes if c.id not in in_any_tree]

    # Subtree leaf-count for centering. A node's "slot width" is the number
    # of leaves under it (every leaf takes one column).
    slot_cache: dict[str, int] = {}

    def slot_width(cid: str) -> int:
        if cid in slot_cache:
            return slot_cache[cid]
        kids = children.get(cid, [])
        if not kids:
            slot_cache[cid] = 1
            return 1
        slot_cache[cid] = sum(slot_width(k) for k in kids)
        return slot_cache[cid]

    def tree_depth(cid: str) -> int:
        kids = children.get(cid, [])
        return 0 if not kids else 1 + max(tree_depth(k) for k in kids)

    # Find each free class's "anchor" — the tree class it relates to via
    # the STRONGEST non-inheritance edge. Free classes get placed at their
    # anchor's y level (to the side of the tree) so the connecting edge is
    # short. Picking the strongest relationship (composition > aggregation
    # > association) anchors the free class to the conceptually closest
    # tree member when multiple edges exist.
    _REL_STRENGTH = {
        "composition": 4,
        "aggregation": 3,
        "realization": 2,
        "association": 2,
        "dependency": 1,
    }
    anchors: dict[str, str] = {}
    for fc in free_classes:
        best: tuple[int, int, str] | None = None  # (strength, -decl_idx, partner)
        for idx_r, r in enumerate(d.relationships):
            if r.type in _HIERARCHY_TYPES:
                continue
            other = r.dst if r.src == fc.id else (r.src if r.dst == fc.id else None)
            if other and other in in_any_tree:
                key = (_REL_STRENGTH.get(r.type, 0), -idx_r, other)
                if best is None or key > best:
                    best = key
        if best is not None:
            anchors[fc.id] = best[2]

    # Anchored free classes: split alternating left/right of their anchor.
    by_anchor: dict[str, list[str]] = defaultdict(list)
    unanchored: list[str] = []
    for fc in free_classes:
        if fc.id in anchors:
            by_anchor[anchors[fc.id]].append(fc.id)
        else:
            unanchored.append(fc.id)

    left_slots: dict[str, list[str]] = defaultdict(list)
    right_slots: dict[str, list[str]] = defaultdict(list)
    for anchor, fcs in by_anchor.items():
        for i, fc in enumerate(fcs):
            (left_slots if i % 2 == 0 else right_slots)[anchor].append(fc)

    max_left = max((len(v) for v in left_slots.values()), default=0)

    positions: dict[str, tuple[float, float]] = {}
    slot = _W + _H_GAP

    # ----- Unanchored free classes: top row, full width --------------------
    cur_y = _MARGIN
    top_row_h = 0
    if unanchored:
        x = _MARGIN
        for cid in unanchored:
            positions[cid] = (x, cur_y)
            x += slot
            top_row_h = max(top_row_h, heights[cid])
        cur_y += top_row_h + _V_GAP

    # ----- Inheritance trees: shifted right to make room for left anchors --
    tree_top_y = cur_y
    cur_x = _MARGIN + max_left * slot

    for comp in components:
        roots = sorted([n for n in comp if not parents.get(n)],
                       key=lambda i: next(j for j, c in enumerate(d.classes)
                                          if c.id == i))
        depth = max((tree_depth(r) for r in roots), default=0)

        level_h: dict[int, float] = defaultdict(float)

        def assign_levels(cid: str, lvl: int) -> None:
            level_h[lvl] = max(level_h[lvl], heights[cid])
            for k in children.get(cid, []):
                assign_levels(k, lvl + 1)

        for r in roots:
            assign_levels(r, 0)

        level_y: dict[int, float] = {}
        y = tree_top_y
        for lvl in range(depth + 1):
            level_y[lvl] = y
            y += level_h[lvl] + _V_GAP

        def place(cid: str, x_left: float, lvl: int) -> None:
            w = slot_width(cid)
            cx = x_left + (w * slot - _H_GAP) / 2 - _W / 2
            positions[cid] = (cx, level_y[lvl])
            kids = children.get(cid, [])
            kx = x_left
            for k in kids:
                kw = slot_width(k)
                place(k, kx, lvl + 1)
                kx += kw * slot

        for r in roots:
            rw = slot_width(r)
            place(r, cur_x, 0)
            cur_x += rw * slot

        cur_x += _H_GAP

    # ----- Anchored free classes: placed to the side of their anchor -------
    for anchor, fcs in left_slots.items():
        anchor_x, anchor_y = positions[anchor]
        for i, fc in enumerate(fcs):
            x = anchor_x - (i + 1) * slot
            positions[fc] = (x, anchor_y)

    for anchor, fcs in right_slots.items():
        anchor_x, anchor_y = positions[anchor]
        for i, fc in enumerate(fcs):
            x = anchor_x + (i + 1) * slot
            positions[fc] = (x, anchor_y)

    # ----- Shapes ----------------------------------------------------------
    shapes: list[Shape] = []
    for c in d.classes:
        x, y = positions[c.id]
        shapes.append(
            Shape(
                id=c.id,
                x=x,
                y=y,
                width=_W,
                height=heights[c.id],
                label=_format_label(c),
                style=_BOX_STYLE,
            )
        )

    # ----- Edges -----------------------------------------------------------
    connectors = []
    for idx, r in enumerate(d.relationships):
        arrow = _REL_END_ARROW.get(r.type, "endArrow=block;")
        style = EDGE_STYLE + arrow
        label = r.label
        if r.multiplicity:
            label = f"{label} {r.multiplicity}".strip()
        conn = make_connector(idx, r.src, r.dst, label, style)
        # UML per-end labels: combine optional role name and multiplicity.
        src_end = " ".join(p for p in (r.source_role, r.source_multiplicity) if p)
        dst_end = " ".join(p for p in (r.target_role, r.target_multiplicity) if p)
        conn.source_label = src_end
        conn.target_label = dst_end
        connectors.append(conn)

    canvas_w = int(max(p[0] + _W for p in positions.values()) + _MARGIN)
    canvas_h = int(
        max(p[1] + heights[cid] for cid, p in positions.items()) + _MARGIN
    )
    return BuildResult(
        title=d.title,
        shapes=shapes,
        connectors=connectors,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
    )
