from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


_Strict = ConfigDict(extra="forbid", populate_by_name=True)


class _Model(BaseModel):
    model_config = _Strict


class NamedNode(_Model):
    """Any node-like element. `id` is the stable handle; `name` is the display label."""

    id: str = Field(min_length=1)
    name: str | None = None

    @model_validator(mode="after")
    def _default_name(self) -> "NamedNode":
        if self.name is None:
            self.name = self.id
        return self


class Edge(_Model):
    """Common base for any directed link. Subclasses add labels/metadata."""

    src: str = Field(alias="from", min_length=1)
    dst: str = Field(alias="to", min_length=1)


# ----------------------------- DFD -----------------------------

DFDEntityType = Literal["external_entity", "process", "store"]


class DFDEntity(NamedNode):
    type: DFDEntityType


class Flow(Edge):
    label: str = Field(min_length=1)


class DFDDiagram(_Model):
    type: Literal["dfd"]
    title: str
    description: str | None = None
    level: int | None = None
    entities: list[DFDEntity]
    flows: list[Flow]


# ---------------------------- Class ----------------------------

RelationshipType = Literal[
    "association",
    "aggregation",
    "composition",
    "inheritance",
    "dependency",
    "realization",
]


class ClassDef(NamedNode):
    attributes: list[str] = []
    methods: list[str] = []
    is_abstract: bool = False
    is_interface: bool = False
    stereotype: str = ""


class Relationship(Edge):
    type: RelationshipType
    label: str = ""
    multiplicity: str = ""
    # Optional UML role labels on each end of the relationship. Rendered
    # near the source/target cell respectively (e.g. "owner" near src,
    # "items" near dst). Different from `label`, which is the
    # relationship name printed at the midpoint.
    source_role: str = ""
    target_role: str = ""
    source_multiplicity: str = ""
    target_multiplicity: str = ""


class ClassDiagram(_Model):
    type: Literal["class"]
    title: str
    description: str | None = None
    classes: list[ClassDef]
    relationships: list[Relationship] = []


# ---------------------------- State ----------------------------


class State(NamedNode):
    is_initial: bool = False
    is_final: bool = False
    # Optional id of a composite parent state. If set, this state renders
    # nested inside that composite. The parent must itself be declared
    # in the states list with no `parent` of its own (one level of
    # nesting supported for now).
    parent: str | None = None
    # UML history pseudo-state. When set, renders as a small "H" circle
    # (shallow) or "H*" circle (deep) inside its composite parent —
    # representing the "last visited sub-state" entry point. Only
    # meaningful when `parent` is also set.
    is_history: bool = False
    history_deep: bool = False


class Transition(Edge):
    event: str = ""
    guard: str = ""
    action: str = ""


class StateDiagram(_Model):
    type: Literal["std"]
    title: str
    description: str | None = None
    states: list[State]
    transitions: list[Transition] = []


# --------------------------- Sequence ---------------------------

SeqObjectType = Literal["actor", "boundary", "control", "entity"]
MessageType = Literal["call", "return", "create", "destroy", "self"]


class SeqObject(NamedNode):
    type: SeqObjectType


class Message(Edge):
    label: str = Field(min_length=1)
    type: MessageType = "call"


FrameType = Literal["loop", "alt", "opt", "par", "break"]


class Frame(_Model):
    """UML interaction frame wrapping a range of messages.

    `from_message` and `to_message` are 0-based indices into the
    diagram's `messages` list (inclusive). `condition` renders as the
    bracketed text after the frame type (e.g. `loop [each item]`).
    """

    type: FrameType
    condition: str = ""
    from_message: int = Field(ge=0)
    to_message: int = Field(ge=0)


class SequenceDiagram(_Model):
    type: Literal["sequence"]
    title: str
    description: str | None = None
    objects: list[SeqObject]
    messages: list[Message] = []
    frames: list[Frame] = []


# --------------------------- Activity ---------------------------

ActivityType = Literal["start", "end", "normal", "decision", "merge", "fork", "join"]


class Swimlane(NamedNode):
    color: str = "#E8F4F8"


class Activity(NamedNode):
    type: ActivityType = "normal"
    swimlane: str = Field(min_length=1)


class ActivityTransition(Edge):
    label: str = ""
    guard: str = ""


class ActivityDiagram(_Model):
    type: Literal["activity"]
    title: str
    description: str | None = None
    swimlanes: list[Swimlane]
    activities: list[Activity]
    transitions: list[ActivityTransition] = []


# ---------------------------- Dialog ----------------------------


class Dialog(NamedNode):
    is_initial: bool = False
    is_final: bool = False
    # See State.parent for semantics.
    parent: str | None = None


class DialogTransition(Edge):
    trigger: str = ""


class DialogDiagram(_Model):
    type: Literal["dialog"]
    title: str
    description: str | None = None
    dialogs: list[Dialog]
    transitions: list[DialogTransition] = []


# ---------------------------- Root ----------------------------


AnyDiagram = Annotated[
    DFDDiagram
    | ClassDiagram
    | StateDiagram
    | SequenceDiagram
    | ActivityDiagram
    | DialogDiagram,
    Field(discriminator="type"),
]


class IR(_Model):
    diagram: AnyDiagram
