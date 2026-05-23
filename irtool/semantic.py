"""Graph-level semantic checks on a parsed IR.

Schema validation (Pydantic) guarantees structural correctness. These checks
operate on the typed model and enforce diagram semantics: no duplicates,
no dangling references, no orphans, plus per-type invariants.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .issues import Issue, IssueCode, error, warning
from .models import (
    IR,
    Activity,
    ActivityDiagram,
    ActivityTransition,
    ClassDef,
    ClassDiagram,
    DFDDiagram,
    DFDEntity,
    Dialog,
    DialogDiagram,
    DialogTransition,
    Edge,
    Flow,
    Message,
    NamedNode,
    Relationship,
    SeqObject,
    SequenceDiagram,
    State,
    StateDiagram,
    Transition,
)


def check(ir: IR) -> list[Issue]:
    """Run all semantic checks. Returns issues in stable order."""
    d = ir.diagram
    if isinstance(d, DFDDiagram):
        issues = _check_dfd(d)
    elif isinstance(d, ClassDiagram):
        issues = _check_class(d)
    elif isinstance(d, StateDiagram):
        issues = _check_state(d)
    elif isinstance(d, SequenceDiagram):
        issues = _check_sequence(d)
    elif isinstance(d, ActivityDiagram):
        issues = _check_activity(d)
    elif isinstance(d, DialogDiagram):
        issues = _check_dialog(d)
    else:  # pragma: no cover
        issues = []
    return sorted(issues, key=lambda i: (i.severity.value, i.path, i.code.value))


# ----------------------------- helpers -----------------------------


def _duplicate_ids(
    nodes: Sequence[NamedNode], base_path: str
) -> list[Issue]:
    seen: dict[str, int] = {}
    out: list[Issue] = []
    for i, n in enumerate(nodes):
        if n.id in seen:
            out.append(
                error(
                    IssueCode.DUPLICATE_ID,
                    f"{base_path}[{i}].id",
                    f"id {n.id!r} already used at {base_path}[{seen[n.id]}]",
                )
            )
        else:
            seen[n.id] = i
    return out


def _dangling_refs(
    edges: Sequence[Edge], valid_ids: set[str], base_path: str
) -> list[Issue]:
    out: list[Issue] = []
    for i, e in enumerate(edges):
        if e.src not in valid_ids:
            out.append(
                error(
                    IssueCode.DANGLING_REF,
                    f"{base_path}[{i}].from",
                    f"{e.src!r} is not a defined node id",
                )
            )
        if e.dst not in valid_ids:
            out.append(
                error(
                    IssueCode.DANGLING_REF,
                    f"{base_path}[{i}].to",
                    f"{e.dst!r} is not a defined node id",
                )
            )
    return out


def _orphans(
    nodes: Sequence[NamedNode],
    edges: Iterable[Edge],
    nodes_path: str,
) -> list[Issue]:
    touched: set[str] = set()
    for e in edges:
        touched.add(e.src)
        touched.add(e.dst)
    out: list[Issue] = []
    for i, n in enumerate(nodes):
        if n.id not in touched:
            out.append(
                error(
                    IssueCode.ORPHAN_NODE,
                    f"{nodes_path}[{i}].id",
                    f"node {n.id!r} is not referenced by any edge",
                )
            )
    return out


def _empty(diagram_path: str, nodes: Sequence[NamedNode]) -> list[Issue]:
    if not nodes:
        return [
            error(
                IssueCode.EMPTY_DIAGRAM,
                diagram_path,
                "diagram has no nodes",
            )
        ]
    return []


# ------------------------------- DFD -------------------------------

_DFD_FORBIDDEN: dict[tuple[str, str], IssueCode] = {
    ("store", "store"): IssueCode.DFD_STORE_TO_STORE,
    ("external_entity", "store"): IssueCode.DFD_EXTERNAL_TO_STORE,
    ("store", "external_entity"): IssueCode.DFD_STORE_TO_EXTERNAL,
    ("external_entity", "external_entity"): IssueCode.DFD_EXTERNAL_TO_EXTERNAL,
}


def _check_dfd(d: DFDDiagram) -> list[Issue]:
    issues: list[Issue] = []
    issues += _empty("diagram.entities", d.entities)
    issues += _duplicate_ids(d.entities, "diagram.entities")

    ids = {e.id for e in d.entities}
    by_id: dict[str, DFDEntity] = {e.id: e for e in d.entities}

    issues += _dangling_refs(d.flows, ids, "diagram.flows")
    issues += _orphans(d.entities, d.flows, "diagram.entities")

    for i, flow in enumerate(d.flows):
        if flow.src in by_id and flow.dst in by_id:
            pair = (by_id[flow.src].type, by_id[flow.dst].type)
            code = _DFD_FORBIDDEN.get(pair)
            if code:
                issues.append(
                    error(
                        code,
                        f"diagram.flows[{i}]",
                        f"flow {flow.src!r} -> {flow.dst!r} is forbidden "
                        f"({pair[0]} -> {pair[1]})",
                    )
                )
    return issues


# ------------------------------ Class ------------------------------


def _check_class(d: ClassDiagram) -> list[Issue]:
    issues: list[Issue] = []
    issues += _empty("diagram.classes", d.classes)
    issues += _duplicate_ids(d.classes, "diagram.classes")

    ids = {c.id for c in d.classes}
    issues += _dangling_refs(d.relationships, ids, "diagram.relationships")
    # Classes do not need to participate in relationships — standalone
    # classes are common. So orphan check is skipped for class diagrams.

    inheritance: dict[str, list[str]] = {c.id: [] for c in d.classes}
    for r in d.relationships:
        if r.type == "inheritance" and r.src in inheritance and r.dst in inheritance:
            inheritance[r.src].append(r.dst)

    cycle = _find_cycle(inheritance)
    if cycle:
        issues.append(
            error(
                IssueCode.INHERITANCE_CYCLE,
                "diagram.relationships",
                f"inheritance cycle: {' -> '.join(cycle)} -> {cycle[0]}",
            )
        )
    return issues


def _find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    parent: dict[str, str | None] = {n: None for n in graph}

    def dfs(start: str) -> list[str] | None:
        stack = [(start, iter(graph.get(start, [])))]
        color[start] = GRAY
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                color[node] = BLACK
                stack.pop()
                continue
            if color.get(nxt) == GRAY:
                cycle = [nxt]
                cur = node
                while cur is not None and cur != nxt:
                    cycle.append(cur)
                    cur = parent[cur]
                cycle.reverse()
                return cycle
            if color.get(nxt) == WHITE:
                parent[nxt] = node
                color[nxt] = GRAY
                stack.append((nxt, iter(graph.get(nxt, []))))
        return None

    for n in graph:
        if color[n] == WHITE:
            found = dfs(n)
            if found:
                return found
    return None


# ------------------------------ State ------------------------------


def _check_state(d: StateDiagram) -> list[Issue]:
    issues: list[Issue] = []
    issues += _empty("diagram.states", d.states)
    issues += _duplicate_ids(d.states, "diagram.states")

    ids = {s.id for s in d.states}
    issues += _dangling_refs(d.transitions, ids, "diagram.transitions")
    issues += _orphans(d.states, d.transitions, "diagram.states")

    initials = [s for s in d.states if s.is_initial]
    if len(initials) == 0:
        issues.append(
            error(
                IssueCode.NO_INITIAL_STATE,
                "diagram.states",
                "no state has is_initial: true",
            )
        )
    elif len(initials) > 1:
        names = ", ".join(s.id for s in initials)
        issues.append(
            error(
                IssueCode.MULTIPLE_INITIAL_STATES,
                "diagram.states",
                f"multiple initial states: {names}",
            )
        )

    if not any(s.is_final for s in d.states):
        issues.append(
            warning(
                IssueCode.NO_FINAL_STATE,
                "diagram.states",
                "no state has is_final: true",
            )
        )

    if len(initials) == 1:
        adj: dict[str, list[str]] = {s.id: [] for s in d.states}
        for t in d.transitions:
            if t.src in adj and t.dst in adj:
                adj[t.src].append(t.dst)
        reachable = _bfs(initials[0].id, adj)
        for i, s in enumerate(d.states):
            if s.id not in reachable:
                issues.append(
                    warning(
                        IssueCode.UNREACHABLE_STATE,
                        f"diagram.states[{i}].id",
                        f"state {s.id!r} not reachable from initial state "
                        f"{initials[0].id!r}",
                    )
                )
    return issues


def _bfs(start: str, adj: dict[str, list[str]]) -> set[str]:
    seen = {start}
    frontier = [start]
    while frontier:
        nxt: list[str] = []
        for n in frontier:
            for m in adj.get(n, []):
                if m not in seen:
                    seen.add(m)
                    nxt.append(m)
        frontier = nxt
    return seen


# ---------------------------- Sequence ----------------------------

_SEQ_RANK = {"actor": 0, "boundary": 1, "control": 2, "entity": 3}


def _check_sequence(d: SequenceDiagram) -> list[Issue]:
    issues: list[Issue] = []
    issues += _empty("diagram.objects", d.objects)
    issues += _duplicate_ids(d.objects, "diagram.objects")

    ids = {o.id for o in d.objects}
    issues += _dangling_refs(d.messages, ids, "diagram.messages")
    issues += _orphans(d.objects, d.messages, "diagram.objects")

    last = -1
    for i, obj in enumerate(d.objects):
        r = _SEQ_RANK[obj.type]
        if r < last:
            issues.append(
                error(
                    IssueCode.SEQ_OBJECT_ORDER,
                    f"diagram.objects[{i}].type",
                    f"object {obj.id!r} of type {obj.type!r} appears after a "
                    f"higher-rank type; expected order "
                    f"actor -> boundary -> control -> entity",
                )
            )
        last = max(last, r)
    return issues


# ---------------------------- Activity ----------------------------


def _check_activity(d: ActivityDiagram) -> list[Issue]:
    issues: list[Issue] = []
    issues += _empty("diagram.activities", d.activities)
    issues += _duplicate_ids(d.swimlanes, "diagram.swimlanes")
    issues += _duplicate_ids(d.activities, "diagram.activities")

    swimlane_ids = {s.id for s in d.swimlanes}
    activity_ids = {a.id for a in d.activities}
    issues += _dangling_refs(d.transitions, activity_ids, "diagram.transitions")
    issues += _orphans(d.activities, d.transitions, "diagram.activities")

    for i, a in enumerate(d.activities):
        if a.swimlane not in swimlane_ids:
            issues.append(
                error(
                    IssueCode.ACTIVITY_UNKNOWN_SWIMLANE,
                    f"diagram.activities[{i}].swimlane",
                    f"activity {a.id!r} references unknown swimlane "
                    f"{a.swimlane!r}",
                )
            )

    starts = [a for a in d.activities if a.type == "start"]
    ends = [a for a in d.activities if a.type == "end"]
    if len(starts) == 0:
        issues.append(
            error(
                IssueCode.NO_START_ACTIVITY,
                "diagram.activities",
                "no activity has type: start",
            )
        )
    elif len(starts) > 1:
        names = ", ".join(a.id for a in starts)
        issues.append(
            error(
                IssueCode.MULTIPLE_START_ACTIVITIES,
                "diagram.activities",
                f"multiple start activities: {names}",
            )
        )
    if len(ends) == 0:
        issues.append(
            error(
                IssueCode.NO_END_ACTIVITY,
                "diagram.activities",
                "no activity has type: end",
            )
        )
    return issues


# ----------------------------- Dialog -----------------------------


def _check_dialog(d: DialogDiagram) -> list[Issue]:
    issues: list[Issue] = []
    issues += _empty("diagram.dialogs", d.dialogs)
    issues += _duplicate_ids(d.dialogs, "diagram.dialogs")

    ids = {x.id for x in d.dialogs}
    issues += _dangling_refs(d.transitions, ids, "diagram.transitions")
    issues += _orphans(d.dialogs, d.transitions, "diagram.dialogs")
    return issues
