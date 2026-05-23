"""Render-layer data types: positioned shapes and connectors."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Shape:
    """A positioned vertex cell in the diagram."""

    id: str
    x: float
    y: float
    width: float
    height: float
    label: str
    style: str
    parent: str = "1"


@dataclass
class Connector:
    """A directed edge between two shapes."""

    id: str
    src: str
    dst: str
    label: str = ""
    style: str = ""
    # Optional pinned attachment points (0..1 relative to box). Use sparingly
    # — only when you need parallel-edge separation; drawio's auto-perimeter
    # is correct for everything else.
    exit_x: float | None = None
    exit_y: float | None = None
    entry_x: float | None = None
    entry_y: float | None = None
    # Explicit absolute waypoints between source and target. Use sparingly
    # — only when auto-routing genuinely can't do the right thing (e.g.
    # self-loops on sequence lifelines).
    waypoints: list[tuple[float, float]] = field(default_factory=list)
    # Label offset (pixels) from the edge midpoint. Used to push parallel
    # edges' labels apart so they don't collide.
    label_offset_x: float = 0.0
    label_offset_y: float = 0.0
    # Optional UML edge-end labels. ``source_label`` renders near the
    # source side of the edge (relative x = -1), ``target_label`` near
    # the target side (relative x = +1). Used for role + multiplicity in
    # class diagrams.
    source_label: str = ""
    target_label: str = ""
    # When set, the primary ``label`` is emitted as a child edgeLabel
    # cell pinned at the given relative-x position along the edge path
    # (range -1..+1, where 0 is the natural midpoint). Useful when
    # drawio's default label placement lands the text on top of other
    # cells — pin it to an empty segment instead. The edge's own value
    # attribute is left blank when this is in effect.
    label_position_x: float | None = None


@dataclass
class BuildResult:
    title: str
    shapes: list[Shape]
    connectors: list[Connector]
    canvas_w: int
    canvas_h: int
    description: str | None = None
