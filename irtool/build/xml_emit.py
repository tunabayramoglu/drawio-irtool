"""Turn a BuildResult into a drawio (mxfile) XML string.

Strictly mechanical. All geometry decisions happen in the per-type builders,
with one exception: a uniform header strip (title + optional description)
is added here so every diagram type renders its title consistently.
"""

from __future__ import annotations

from dataclasses import replace

from lxml import etree

from .types import BuildResult, Connector, Shape


_TITLE_H = 36
_DESC_H = 28
_HEADER_TOP = 16
_HEADER_BOTTOM = 20
_HEADER_SIDE_PAD = 20

_TITLE_STYLE = (
    "text;html=1;align=center;verticalAlign=middle;"
    "fontSize=18;fontStyle=1;strokeColor=none;fillColor=none;"
)
_DESC_STYLE = (
    "text;html=1;align=center;verticalAlign=middle;"
    "fontSize=12;fontStyle=2;fontColor=#666666;"
    "strokeColor=none;fillColor=none;"
)


def _header_offset(result: BuildResult) -> int:
    """Total vertical space the header strip will consume."""
    if not result.title and not result.description:
        return 0
    h = _HEADER_TOP
    if result.title:
        h += _TITLE_H
    if result.description:
        h += _DESC_H
    h += _HEADER_BOTTOM
    return h


def _apply_header(
    result: BuildResult,
) -> tuple[list[Shape], list[Connector], int]:
    """Insert title/description text cells above the diagram and shift
    every existing top-level shape and every connector waypoint down by
    the header height. Children of swimlanes (parent != "1") are
    positioned relative to their parent — those don't move."""
    offset = _header_offset(result)
    if offset == 0:
        return list(result.shapes), list(result.connectors), result.canvas_h

    header_shapes: list[Shape] = []
    y = _HEADER_TOP
    inner_w = result.canvas_w - 2 * _HEADER_SIDE_PAD
    if result.title:
        header_shapes.append(
            Shape(
                id="__title__",
                x=_HEADER_SIDE_PAD,
                y=y,
                width=inner_w,
                height=_TITLE_H,
                label=result.title,
                style=_TITLE_STYLE,
            )
        )
        y += _TITLE_H
    if result.description:
        header_shapes.append(
            Shape(
                id="__description__",
                x=_HEADER_SIDE_PAD,
                y=y,
                width=inner_w,
                height=_DESC_H,
                label=result.description,
                style=_DESC_STYLE,
            )
        )

    shifted_shapes: list[Shape] = []
    for s in result.shapes:
        if s.parent == "1":
            shifted_shapes.append(replace(s, y=s.y + offset))
        else:
            shifted_shapes.append(s)

    shifted_connectors: list[Connector] = []
    for c in result.connectors:
        if c.waypoints:
            shifted_connectors.append(
                replace(c, waypoints=[(wx, wy + offset) for wx, wy in c.waypoints])
            )
        else:
            shifted_connectors.append(c)

    return (
        header_shapes + shifted_shapes,
        shifted_connectors,
        result.canvas_h + offset,
    )


def emit_xml(result: BuildResult) -> str:
    shapes, connectors, canvas_h = _apply_header(result)
    # Replace the canvas_h used downstream so page geometry matches the
    # post-header layout. The result object itself is left untouched.
    canvas_w = result.canvas_w
    mxfile = etree.Element(
        "mxfile",
        host="irtool",
        agent="irtool",
        version="1.0.0",
    )
    diagram_el = etree.SubElement(mxfile, "diagram", name=result.title, id="d1")
    model = etree.SubElement(
        diagram_el,
        "mxGraphModel",
        dx=str(canvas_w),
        dy=str(canvas_h),
        grid="1",
        gridSize="10",
        guides="1",
        tooltips="1",
        connect="1",
        arrows="1",
        fold="1",
        page="1",
        pageScale="1",
        pageWidth=str(canvas_w),
        pageHeight=str(canvas_h),
    )
    root = etree.SubElement(model, "root")

    etree.SubElement(root, "mxCell", id="0")
    parent_cell = etree.SubElement(root, "mxCell", id="1", parent="0")
    etree.SubElement(
        parent_cell,
        "mxGeometry",
        width=str(canvas_w),
        height=str(canvas_h),
    ).set("as", "geometry")

    for shape in shapes:
        _emit_shape(root, shape)
    for conn in connectors:
        _emit_connector(root, conn)

    return etree.tostring(
        mxfile, pretty_print=True, xml_declaration=True, encoding="UTF-8"
    ).decode("utf-8")


def _emit_shape(root: etree._Element, s: Shape) -> None:
    cell = etree.SubElement(
        root,
        "mxCell",
        id=s.id,
        value=s.label,
        style=s.style,
        vertex="1",
        parent=s.parent,
    )
    geom = etree.SubElement(
        cell,
        "mxGeometry",
        x=str(s.x),
        y=str(s.y),
        width=str(s.width),
        height=str(s.height),
    )
    geom.set("as", "geometry")


_EDGE_LABEL_STYLE = (
    "edgeLabel;html=1;align=center;verticalAlign=middle;"
    "resizable=0;points=[];fontSize=11;"
)


def _emit_connector(root: etree._Element, c: Connector) -> None:
    style = c.style
    if c.exit_x is not None and c.exit_y is not None:
        style += f";exitX={c.exit_x};exitY={c.exit_y};exitDx=0;exitDy=0"
    if c.entry_x is not None and c.entry_y is not None:
        style += f";entryX={c.entry_x};entryY={c.entry_y};entryDx=0;entryDy=0"
    # If a pinned label position is requested, the label is emitted as a
    # child edgeLabel cell (below) instead of as this edge's value.
    edge_value = "" if c.label_position_x is not None else c.label
    cell = etree.SubElement(
        root,
        "mxCell",
        id=c.id,
        value=edge_value,
        style=style,
        edge="1",
        parent="1",
        source=c.src,
        target=c.dst,
    )
    geom = etree.SubElement(cell, "mxGeometry")
    geom.set("relative", "1")
    geom.set("as", "geometry")
    if c.waypoints:
        arr = etree.SubElement(geom, "Array")
        arr.set("as", "points")
        for wx, wy in c.waypoints:
            pt = etree.SubElement(arr, "mxPoint")
            pt.set("x", str(int(wx)))
            pt.set("y", str(int(wy)))
    if c.label_offset_x or c.label_offset_y:
        off = etree.SubElement(geom, "mxPoint")
        off.set("x", str(int(c.label_offset_x)))
        off.set("y", str(int(c.label_offset_y)))
        off.set("as", "offset")

    # Pinned primary label.
    if c.label_position_x is not None and c.label:
        sub = etree.SubElement(
            root,
            "mxCell",
            id=f"__lbl_{c.id}__",
            value=c.label,
            style=_EDGE_LABEL_STYLE,
            vertex="1",
            connectable="0",
            parent=c.id,
        )
        sub_geom = etree.SubElement(
            sub,
            "mxGeometry",
            x=f"{c.label_position_x}",
            y="0",
        )
        sub_geom.set("relative", "1")
        sub_geom.set("as", "geometry")
        sub_offset = etree.SubElement(sub_geom, "mxPoint")
        sub_offset.set("x", str(int(c.label_offset_x)))
        sub_offset.set("y", str(int(c.label_offset_y)))
        sub_offset.set("as", "offset")

    # Per-end labels (UML role / multiplicity at source and target sides).
    # Each is a child mxCell with style=edgeLabel positioned along the
    # edge — x=-0.85 sits just inboard of the source endpoint (so the
    # label hugs the edge near the source cell without spilling into it),
    # x=+0.85 is the symmetric position near the target.
    for end_label, rel_x, suffix in (
        (c.source_label, -0.85, "_src"),
        (c.target_label, 0.85, "_tgt"),
    ):
        if not end_label:
            continue
        sub = etree.SubElement(
            root,
            "mxCell",
            id=f"__lbl_{c.id}{suffix}__",
            value=end_label,
            style=_EDGE_LABEL_STYLE,
            vertex="1",
            connectable="0",
            parent=c.id,
        )
        sub_geom = etree.SubElement(
            sub,
            "mxGeometry",
            x=f"{rel_x}",
            y="0",
        )
        sub_geom.set("relative", "1")
        sub_geom.set("as", "geometry")
        sub_offset = etree.SubElement(sub_geom, "mxPoint")
        # Nudge labels off the edge line so the arrow doesn't cut through
        # the text. Up for source-end, down for target-end keeps each
        # pair vertically separated.
        sub_offset.set("x", "0")
        sub_offset.set("y", "-14" if rel_x < 0 else "14")
        sub_offset.set("as", "offset")
