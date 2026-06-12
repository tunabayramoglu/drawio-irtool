"""Sequence diagram: lifelines (shape=umlLifeline) + horizontal messages.

Each SeqObject becomes ONE cell — the umlLifeline shape which draws both
the participant header at the top and the dashed lifeline below in a single
unit. Messages are edges with pinned exit/entry Y so they sit at known
heights along the lifelines.
"""

from __future__ import annotations

from ..models import SequenceDiagram
from ._common import make_connector
from .types import BuildResult, Shape


# Plain labeled headers per object type — drop the participant= icon
# stencils because they don't shrink cleanly into a narrow lifeline width.
# A coloured rectangle header is unambiguous and renders consistently.
_LIFELINE_BASE = (
    "shape=umlLifeline;perimeter=lifelinePerimeter;container=1;"
    "dropTarget=0;size=40;fontSize=13;fontStyle=1;fontColor=#FFFFFF;"
)
_LIFELINE_STYLE = {
    "actor": _LIFELINE_BASE + "fillColor=#2c3e50;strokeColor=#2c3e50;",
    "boundary": _LIFELINE_BASE + "fillColor=#34495e;strokeColor=#34495e;",
    "control": _LIFELINE_BASE + "fillColor=#1a1a1a;strokeColor=#1a1a1a;",
    "entity": _LIFELINE_BASE + "fillColor=#3d3d3d;strokeColor=#3d3d3d;",
}


_MSG_STYLE = {
    "call": "html=1;endArrow=block;endFill=1;strokeWidth=1.5;fontSize=12;",
    "return": "html=1;endArrow=open;dashed=1;strokeWidth=1;fontSize=12;",
    "create": (
        "html=1;endArrow=block;endFill=1;strokeWidth=1.5;fontSize=12;dashed=1;"
    ),
    "destroy": "html=1;endArrow=cross;strokeWidth=1.5;fontSize=12;",
    # Self-messages need orthogonal routing so the (exit_y, entry_y)
    # offset draws a visible arc out to the right of the lifeline and
    # back, instead of degenerating to a vertical stub.
    "self": (
        "edgeStyle=orthogonalEdgeStyle;html=1;endArrow=block;endFill=1;"
        "strokeWidth=1.5;fontSize=12;jettySize=auto;orthogonalLoop=1;"
    ),
}


_LIFELINE_W = 240
_HEADER_H = 40
_INITIAL_GAP = 40
_MSG_GAP = 55
_BOTTOM_PAD = 40
# Left-edge-to-left-edge. Needs to be wide enough that long message
# labels (centred on the arrow) don't overflow into adjacent lifelines.
_X_GAP = 360
_MARGIN = 60

# Activation bar geometry. A bar is a thin vertical rectangle drawn on
# the lifeline showing the period during which that object is "active"
# (between receiving a call and sending the next message).
_ACT_W = 12
_ACT_STYLE = (
    "rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;"
    "strokeColor=#000000;strokeWidth=1.5;"
)


def _activations(d: SequenceDiagram) -> list[tuple[str, int, int]]:
    """Return (lifeline_id, start_msg_idx, end_msg_idx) intervals.

    An activation begins on a lifeline at the message where it first
    *receives* a call after being idle, and ends at the message where
    it next *sends*. If no such send exists, the activation runs to
    the bottom of the diagram (end_msg_idx = len(messages)).

    Self-messages don't start or end an activation — they're handled as
    intra-activation work.
    """
    out: list[tuple[str, int, int]] = []
    active_since: dict[str, int] = {}
    m = len(d.messages)
    for i, msg in enumerate(d.messages):
        if msg.src == msg.dst:
            continue
        # Receiving a call: start an activation if not already active.
        if msg.dst not in active_since:
            active_since[msg.dst] = i
        # Sending a message: close that lifeline's activation here.
        if msg.src in active_since:
            out.append((msg.src, active_since.pop(msg.src), i))
    # Any still-open activations run to the end of the diagram.
    for lid, start in active_since.items():
        out.append((lid, start, m))
    return out


_FRAME_STYLE = (
    "rounded=0;whiteSpace=wrap;html=1;fillColor=none;strokeColor=#888888;"
    "strokeWidth=1.5;verticalAlign=top;align=left;spacingTop=22;"
    "spacingLeft=8;fontSize=11;fontStyle=0;dashed=0;"
)


def build(d: SequenceDiagram) -> BuildResult:
    n = len(d.objects)
    m = len(d.messages)
    lifeline_h = _HEADER_H + _INITIAL_GAP + max(m, 1) * _MSG_GAP + _BOTTOM_PAD

    # Position lookup for lifelines.
    lifeline_x: dict[str, float] = {
        obj.id: _MARGIN + i * _X_GAP for i, obj in enumerate(d.objects)
    }

    shapes: list[Shape] = []

    # Frames render UNDERNEATH lifelines and messages, so emit first.
    def _msg_y_abs(idx: int) -> float:
        return _MARGIN + _HEADER_H + _INITIAL_GAP + idx * _MSG_GAP

    for fi, frame in enumerate(d.frames):
        a = max(0, frame.from_message)
        b = min(m - 1, frame.to_message)
        if a > b:
            continue
        # Lifelines touched by messages in [a..b].
        involved: set[str] = set()
        for i in range(a, b + 1):
            msg = d.messages[i]
            involved.add(msg.src)
            involved.add(msg.dst)
        if not involved:
            continue
        xs = [lifeline_x[lid] for lid in involved if lid in lifeline_x]
        if not xs:
            continue
        x_min = min(xs) - 28
        x_max = max(xs) + _LIFELINE_W + 28
        y_top = _msg_y_abs(a) - 28
        y_bot = _msg_y_abs(b) + 22
        label = f"<b>{frame.type}</b>"
        if frame.condition:
            label += f" [{frame.condition}]"
        shapes.append(
            Shape(
                id=f"__frame_{fi}__",
                x=x_min,
                y=y_top,
                width=x_max - x_min,
                height=y_bot - y_top,
                label=label,
                style=_FRAME_STYLE,
            )
        )

    for i, obj in enumerate(d.objects):
        x = _MARGIN + i * _X_GAP
        shapes.append(
            Shape(
                id=obj.id,
                x=x,
                y=_MARGIN,
                width=_LIFELINE_W,
                height=lifeline_h,
                label=obj.name or obj.id,
                style=_LIFELINE_STYLE[obj.type],
            )
        )

    # Activation bars: thin rectangles on each lifeline marking when the
    # object is "active". Placed BEFORE messages in shape order so message
    # arrows draw on top.
    def _msg_y(idx: int) -> float:
        return _MARGIN + _HEADER_H + _INITIAL_GAP + idx * _MSG_GAP

    lifeline_by_id = {s.id: s for s in shapes}
    for lid, start_i, end_i in _activations(d):
        if lid not in lifeline_by_id:
            continue
        lifeline = lifeline_by_id[lid]
        top_y = _msg_y(start_i) - 6
        bot_y = (
            _msg_y(end_i)
            if end_i < len(d.messages)
            else _MARGIN + lifeline_h - _BOTTOM_PAD / 2
        )
        h = max(20, bot_y - top_y)
        cx = lifeline.x + lifeline.width / 2
        shapes.append(
            Shape(
                id=f"__act_{lid}_{start_i}__",
                x=cx - _ACT_W / 2,
                y=top_y,
                width=_ACT_W,
                height=h,
                label="",
                style=_ACT_STYLE,
            )
        )

    connectors = []
    # Build bar shape lookup: for a (lifeline_id, msg_idx) where the
    # lifeline has an activation bar spanning that message, return the
    # bar's shape id and its top Y coordinate. Messages exit from the
    # lifeline cell (src always lifeline) and enter at the activation
    # bar's edge when one exists, otherwise enter at the lifeline.
    acts = _activations(d)
    bar_info: dict[tuple[str, int], tuple[str, float, float]] = {}
    for lid, start_i, end_i in acts:
        bar_id = f"__act_{lid}_{start_i}__"
        top_y = _msg_y(start_i) - 6
        bar_h = (
            (_msg_y(end_i) if end_i < m else _MARGIN + lifeline_h - _BOTTOM_PAD / 2)
            - top_y
        )
        for mi in range(start_i, min(end_i, m) + 1):
            bar_info[(lid, mi)] = (bar_id, top_y, bar_h)

    for idx, msg in enumerate(d.messages):
        ratio_lifeline = (_HEADER_H + _INITIAL_GAP + idx * _MSG_GAP) / lifeline_h
        style = _MSG_STYLE.get(msg.type, _MSG_STYLE["call"])
        if msg.src == msg.dst:
            arc_y_up = _MARGIN + ratio_lifeline * lifeline_h
            arc_y_down = arc_y_up + 40
            lifeline_right = next(
                s.x + s.width for s in shapes if s.id == msg.src
            )
            arc_x = lifeline_right + 40
            ratio_down = (arc_y_down - _MARGIN) / lifeline_h
            track = (1.0, ratio_lifeline, 1.0, min(ratio_down, 1.0))
            connector = make_connector(
                idx, msg.src, msg.dst, msg.label, style, track
            )
            connector.waypoints = [(arc_x, arc_y_up), (arc_x, arc_y_down)]
            connectors.append(connector)
        else:
            src_i = d.objects.index(next(o for o in d.objects if o.id == msg.src))
            dst_i = d.objects.index(next(o for o in d.objects if o.id == msg.dst))
            # Source = lifeline cell (perimeter=lifelinePerimeter handles
            # the centered exit pin for us).
            src_cell = msg.src
            exit_x = 0.5
            exit_y = ratio_lifeline
            # Target = activation bar when one exists at this message idx,
            # otherwise fall back to the destination lifeline cell.
            dst_entry = bar_info.get((msg.dst, idx))
            if dst_entry is not None:
                dst_cell, bar_top, bar_h = dst_entry
                msg_abs_y = _msg_y(idx)
                entry_y = (msg_abs_y - bar_top) / max(bar_h, 1)
                entry_x = 0.0 if src_i < dst_i else 1.0
            else:
                dst_cell = msg.dst
                entry_x = 0.5
                entry_y = ratio_lifeline
            track = (exit_x, exit_y, entry_x, entry_y)
            c = make_connector(idx, src_cell, dst_cell, msg.label, style, track)
            connectors.append(c)

    canvas_w = _MARGIN + (n - 1) * _X_GAP + _LIFELINE_W + _MARGIN
    canvas_h = _MARGIN + lifeline_h + _MARGIN
    return BuildResult(
        title=d.title,
        shapes=shapes,
        connectors=connectors,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
    )
