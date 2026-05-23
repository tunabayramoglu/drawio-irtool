"""Shared helpers across builders."""

from __future__ import annotations

from collections.abc import Iterable

from ..models import Edge
from .types import Connector, Shape


EDGE_STYLE = (
    "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;"
    "jettySize=auto;html=1;fontSize=12;fontStyle=0;endArrow=block;"
)

# Straight (non-orthogonal) edge — used for diagonal bidirectional pairs
# where orthogonal routing forces the two edges to cross.
STRAIGHT_EDGE_STYLE = (
    "html=1;fontSize=12;fontStyle=0;endArrow=block;rounded=0;"
)


_INITIAL_PSEUDO_STYLE = (
    "ellipse;fillColor=#000000;strokeColor=#000000;html=1;"
)
_FINAL_PSEUDO_STYLE = (
    "ellipse;shape=endState;fillColor=#000000;strokeColor=#000000;"
    "fillColor=#ffffff;perimeter=ellipsePerimeter;html=1;"
)
_PSEUDO_SIZE = 24


def initial_pseudo(node_id: str, node_x: float, node_y: float,
                   node_w: float) -> tuple[Shape, Connector]:
    """Build a filled-black-dot pseudo-state above the node, with an
    arrow pointing into it. The pseudo-state id is namespaced so it
    can't collide with user IDs."""
    pseudo_id = f"__init__{node_id}"
    pseudo = Shape(
        id=pseudo_id,
        x=node_x + (node_w - _PSEUDO_SIZE) / 2,
        y=node_y - 70,
        width=_PSEUDO_SIZE,
        height=_PSEUDO_SIZE,
        label="",
        style=_INITIAL_PSEUDO_STYLE,
    )
    conn = Connector(
        id=f"__init_edge__{node_id}",
        src=pseudo_id,
        dst=node_id,
        label="",
        style=EDGE_STYLE,
    )
    return pseudo, conn


def final_pseudo(node_id: str, node_x: float, node_y: float,
                 node_w: float, node_h: float,
                 label: str = "") -> tuple[Shape, Connector]:
    """Build a bullseye pseudo-state BELOW the node, with an arrow
    pointing from the node into it. Placed below rather than to the
    right because the right side can be occupied by sibling cells."""
    pseudo_id = f"__final__{node_id}"
    pseudo = Shape(
        id=pseudo_id,
        x=node_x + (node_w - _PSEUDO_SIZE) / 2,
        y=node_y + node_h + 60,
        width=_PSEUDO_SIZE,
        height=_PSEUDO_SIZE,
        label="",
        style=_FINAL_PSEUDO_STYLE,
    )
    conn = Connector(
        id=f"__final_edge__{node_id}",
        src=node_id,
        dst=pseudo_id,
        label=label,
        style=EDGE_STYLE,
    )
    return pseudo, conn


def outside_route(
    src_pos: tuple[float, float],
    src_size: tuple[float, float],
    dst_pos: tuple[float, float],
    dst_size: tuple[float, float],
    gutter_x: float,
) -> tuple[
    tuple[float, float, float, float],   # (exit_x, exit_y, entry_x, entry_y)
    list[tuple[float, float]],            # absolute waypoints
]:
    """Route an edge around the outside gutter at gutter_x rather than
    through the diagram interior.

    If gutter_x is to the LEFT of both shapes, the edge exits and re-enters
    on the left side (x=0). Otherwise on the right side (x=1). Two waypoints
    are placed in the gutter at the source's and target's vertical centers.
    """
    sx, sy = src_pos
    sw, sh = src_size
    dx, dy = dst_pos
    dw, dh = dst_size
    src_cy = sy + sh / 2
    dst_cy = dy + dh / 2

    if gutter_x < min(sx, dx):
        track = (0.0, 0.5, 0.0, 0.5)
    else:
        track = (1.0, 0.5, 1.0, 0.5)

    waypoints = [(gutter_x, src_cy), (gutter_x, dst_cy)]
    return track, waypoints


def find_bidirectional(edges: Iterable[Edge]) -> set[tuple[str, str]]:
    """Return the set of (src, dst) pairs whose reverse also exists.

    Used to apply track separation so opposing edges don't render on top
    of each other.
    """
    seen: set[tuple[str, str]] = set()
    bidir: set[tuple[str, str]] = set()
    for e in edges:
        if (e.dst, e.src) in seen:
            bidir.add((e.src, e.dst))
            bidir.add((e.dst, e.src))
        seen.add((e.src, e.dst))
    return bidir


def parallel_label_offset(
    src: str,
    dst: str,
    src_x: float,
    dst_x: float,
    src_y: float,
    dst_y: float,
    separation: float = 24,
) -> tuple[float, float]:
    """Label offset to apply to one half of a bidirectional pair, so the
    pair's two labels don't collide at the shared edge midpoint AND
    don't sit directly on top of the arrow line.

    Horizontal pair: edges run on Y tracks 0.3 / 0.7. Labels default to
    sitting on the line, so the arrow visibly cuts through the text.
    Push each label off its own line — the upper-track label goes UP,
    the lower-track label goes DOWN. Track is decided lexically, so we
    mirror that here.

    Vertical pair: both edges have the same midpoint Y. Push each
    label toward its own source so they fan out vertically.
    """
    if abs(dst_x - src_x) >= abs(dst_y - src_y):
        # Horizontal pair. Lex-first src rides the upper track (y=0.3);
        # push its label up. Lex-second rides lower (y=0.7); push down.
        return 0.0, (-separation if src < dst else separation)
    # Vertical pair: source above target -> downward edge -> label up.
    return 0.0, (-separation if src_y <= dst_y else separation)


def parallel_track(
    src: str,
    dst: str,
    src_x: float,
    dst_x: float,
    src_y: float | None = None,
    dst_y: float | None = None,
) -> tuple[float, float, float, float]:
    """Pinned (exit_x, exit_y, entry_x, entry_y) for one half of a
    bidirectional pair.

    The two edges of a pair both attach to the *facing* sides of each
    cell (the side of src nearest dst, and vice versa). They differ
    only in inner/outer position within that side, so neither edge
    has to backtrack across the cell.

    - Horizontal pair: attach on left/right faces, differ on Y track.
    - Vertical pair:   attach on top/bottom faces, differ on X track.
      The natural side of src for the X pin is the side facing dst.
    - Cells stacked directly (no horizontal offset): use lex track.
    """
    track = 0.3 if src < dst else 0.7
    dx = dst_x - src_x
    if src_y is None or dst_y is None:
        if dx >= 0:
            return 1.0, track, 0.0, track
        return 0.0, track, 1.0, track
    dy = dst_y - src_y

    if abs(dx) >= abs(dy):
        # Horizontal pair: tracks differ in Y, edges exit/enter sides.
        if dx >= 0:
            return 1.0, track, 0.0, track
        return 0.0, track, 1.0, track

    # Vertical pair.
    if dx == 0:
        # Directly stacked — no geometric preference. Fall back to lex
        # track on left/right.
        if dy >= 0:
            return track, 1.0, track, 0.0
        return track, 0.0, track, 1.0

    # Diagonal vertical pair. Natural side of src is the side facing dst;
    # natural side of dst is the side facing src. Differentiate the two
    # edges of the pair by using inner vs outer x positions on those sides.
    is_lex_first = src < dst
    if dx > 0:
        # dst is to the right -> natural side of src is RIGHT (x>0.5),
        # natural side of dst is LEFT (x<0.5).
        src_x_pin = 0.85 if is_lex_first else 0.65
        dst_x_pin = 0.15 if is_lex_first else 0.35
    else:
        # dst is to the left -> natural side of src is LEFT, dst is RIGHT.
        src_x_pin = 0.15 if is_lex_first else 0.35
        dst_x_pin = 0.85 if is_lex_first else 0.65

    if dy >= 0:
        return src_x_pin, 1.0, dst_x_pin, 0.0
    return src_x_pin, 0.0, dst_x_pin, 1.0


def make_connector(
    idx: int,
    src: str,
    dst: str,
    label: str,
    style: str = EDGE_STYLE,
    track: tuple[float, float, float, float] | None = None,
) -> Connector:
    c = Connector(
        id=f"e_{idx}",
        src=src,
        dst=dst,
        label=label,
        style=style,
    )
    if track:
        c.exit_x, c.exit_y, c.entry_x, c.entry_y = track
    return c


_COMPOSITE_STYLE = (
    "rounded=1;arcSize=20;whiteSpace=wrap;html=1;container=1;"
    "fillColor=#f8f8f8;strokeColor=#888888;fontSize=14;fontStyle=1;"
    "verticalAlign=top;spacingTop=6;dashed=0;"
)
_COMPOSITE_PAD = 30
_COMPOSITE_HEADER = 32


def apply_composites(
    shapes: list[Shape], parent_of: dict[str, str | None]
) -> list[Shape]:
    """Wrap children of each composite in a container Shape and convert
    child coordinates to be relative to that container.

    ``parent_of`` maps every node id to its declared composite parent id
    (or None). Composite parents themselves must already exist as Shapes
    in ``shapes`` — this function repositions and resizes them to wrap
    their children and reparents children to them in the drawio sense.

    Returns the (possibly reordered) shapes list. Connectors are
    untouched because their endpoints reference cell ids, not positions.
    """
    if not any(parent_of.values()):
        return shapes

    by_id = {s.id: s for s in shapes}
    children_of: dict[str, list[str]] = {}
    for cid, pid in parent_of.items():
        if pid and pid in by_id:
            children_of.setdefault(pid, []).append(cid)

    for parent_id, kids in children_of.items():
        parent = by_id[parent_id]
        # Bounding box of children's current absolute positions.
        min_x = min(by_id[k].x for k in kids)
        min_y = min(by_id[k].y for k in kids)
        max_x = max(by_id[k].x + by_id[k].width for k in kids)
        max_y = max(by_id[k].y + by_id[k].height for k in kids)

        new_x = min_x - _COMPOSITE_PAD
        new_y = min_y - _COMPOSITE_HEADER - _COMPOSITE_PAD
        new_w = (max_x - min_x) + 2 * _COMPOSITE_PAD
        new_h = (max_y - min_y) + _COMPOSITE_HEADER + 2 * _COMPOSITE_PAD

        parent.x = new_x
        parent.y = new_y
        parent.width = new_w
        parent.height = new_h
        parent.style = _COMPOSITE_STYLE
        # Reparent children: their coordinates become relative to parent.
        for k in kids:
            child = by_id[k]
            child.parent = parent_id
            child.x = child.x - new_x
            child.y = child.y - new_y

    return shapes
