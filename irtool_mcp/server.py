"""MCP server for irtool.

Exposes the validate -> build -> render pipeline as MCP tools so any MCP
client (Claude Desktop, Claude Code, Cursor, IDE plugins, custom agents)
can generate, validate, and render irtool YAML diagrams.

Transport: stdio (the MCP default). Configure a client with:

    {
      "mcpServers": {
        "irtool": {
          "command": "python",
          "args": ["-m", "irtool_mcp"],
          "env": {"DRAWIO_EXPORT_URL": "http://localhost:8005"}
        }
      }
    }

The `DRAWIO_EXPORT_URL` env var is only needed if you want render_diagram
to work — without it, validate_diagram and build_diagram still function.
"""

from __future__ import annotations

import base64
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from irtool.build import ir_to_xml
from irtool.render import RenderError, Renderer
from irtool.validate import parse_and_validate, validate_text


mcp = FastMCP("irtool")


# Bundled minimal examples (one per diagram type), shipped with the
# package so get_example() works after `pip install` without depending
# on the repo's tests/ directory.
_EXAMPLES_DIR = Path(__file__).resolve().parent / "examples"


_TYPE_DOCS: dict[str, str] = {
    "dfd": (
        "Data Flow Diagram. Top-level keys: type, title, entities, flows. "
        "Each entity has id and type (external_entity|process|store). "
        "Forbidden flow combinations are rejected (store↔store, "
        "external↔store, external↔external)."
    ),
    "class": (
        "UML class diagram. Top-level keys: type, title, classes, "
        "relationships. Classes have id, name, attributes, methods, "
        "is_abstract. Relationships use type ∈ "
        "{inheritance, realization, composition, aggregation, "
        "association, dependency} with optional label and multiplicity."
    ),
    "std": (
        "State Transition Diagram. Top-level keys: type, title, states, "
        "transitions. States flag is_initial / is_final (rendered as "
        "pseudo-states). Transitions carry event, guard, action."
    ),
    "sequence": (
        "UML sequence diagram. Top-level keys: type, title, objects, "
        "messages. Objects MUST appear in order actor -> boundary -> "
        "control -> entity (validator enforces this)."
    ),
    "activity": (
        "Activity / swimlane diagram. Top-level keys: type, title, "
        "swimlanes, activities, transitions. Activity types: "
        "start|end|normal|decision|merge|fork|join. Each activity is "
        "assigned to one swimlane by id. Long edges route through "
        "lane-boundary channels automatically."
    ),
    "dialog": (
        "Dialog / screen-flow map. Top-level keys: type, title, "
        "dialogs, transitions. Same is_initial/is_final pseudo-state "
        "convention as STD. Layout is spine-aware: shortest "
        "initial->final path defines the main column; bidir loops are "
        "side-steps; one-way exceptions branch."
    ),
}


def _issues_to_dicts(issues: list) -> list[dict]:
    return [
        {
            "severity": i.severity.value,
            "code": i.code.value,
            "path": i.path,
            "message": i.message,
        }
        for i in issues
    ]


@mcp.tool()
def validate_diagram(yaml_content: str) -> dict:
    """Validate an irtool YAML diagram.

    Runs schema (Pydantic, strict — unknown fields are errors) and
    semantic (per-type invariants, orphan/dangling checks) layers.

    Returns:
        {
          "ok": bool,                 # True iff no error-severity issues
          "error_count": int,
          "warning_count": int,
          "issues": [                 # ordered by severity, path
            {"severity", "code", "path", "message"}, ...
          ]
        }

    Issue codes are stable identifiers (e.g. "orphan_node",
    "duplicate_id", "dfd_store_to_store") suitable for programmatic
    recovery — an LLM can read the code and fix the YAML accordingly.
    """
    issues = validate_text(yaml_content)
    errors = sum(1 for i in issues if i.severity.value == "error")
    warnings = sum(1 for i in issues if i.severity.value == "warning")
    return {
        "ok": errors == 0,
        "error_count": errors,
        "warning_count": warnings,
        "issues": _issues_to_dicts(issues),
    }


@mcp.tool()
def build_diagram(yaml_content: str) -> dict:
    """Build an irtool YAML diagram into drawio XML.

    Validates first; if any error-severity issue is found, returns the
    issue list instead of XML. On success, returns the drawio XML
    string (paste-ready into draw.io: File > Open > paste, or save as
    .drawio).

    Returns:
        On success: {"ok": True, "drawio_xml": "<mxfile ...>"}
        On failure: {"ok": False, "issues": [...]}
    """
    issues, ir = parse_and_validate(yaml_content)
    if any(i.severity.value == "error" for i in issues):
        return {"ok": False, "issues": _issues_to_dicts(issues)}
    return {"ok": True, "drawio_xml": ir_to_xml(ir)}


@mcp.tool()
def render_diagram(yaml_content: str, scale: float = 1.0) -> dict:
    """Build and render an irtool YAML diagram to a PNG image.

    Requires the drawio export server to be reachable (set
    DRAWIO_EXPORT_URL env var, default http://localhost:8005).

    Args:
        yaml_content: the irtool YAML source.
        scale: PNG render scale (1.0 = native, 2.0 = retina, etc.).

    Returns:
        On success: {
            "ok": True,
            "drawio_xml": "<mxfile ...>",
            "png_base64": "<base64-encoded PNG bytes>",
            "png_size_bytes": int
        }
        On validation failure: {"ok": False, "issues": [...]}
        On render failure: {"ok": False, "error": "..."}
    """
    built = build_diagram(yaml_content)
    if not built.get("ok"):
        return built
    xml = built["drawio_xml"]
    try:
        renderer = Renderer()
        if not renderer.health():
            return {
                "ok": False,
                "error": (
                    f"drawio export server unreachable at {renderer.endpoint}. "
                    f"Start it locally or set DRAWIO_EXPORT_URL."
                ),
                "drawio_xml": xml,
            }
        png_bytes = renderer.render_png(xml, scale=scale)
    except RenderError as e:
        return {"ok": False, "error": str(e), "drawio_xml": xml}
    return {
        "ok": True,
        "drawio_xml": xml,
        "png_base64": base64.b64encode(png_bytes).decode("ascii"),
        "png_size_bytes": len(png_bytes),
    }


@mcp.tool()
def list_diagram_types() -> dict:
    """List the diagram types irtool supports, with a brief description
    of each type's IR shape and validation rules.

    Returns:
        {"types": {<type_name>: <docstring>, ...}}

    Pair this with get_example(diagram_type) to fetch a working YAML
    skeleton for any listed type.
    """
    return {"types": dict(_TYPE_DOCS)}


@mcp.tool()
def get_example(diagram_type: str) -> dict:
    """Return a minimal valid YAML example for the given diagram type.

    Args:
        diagram_type: one of dfd, class, std, sequence, activity, dialog.

    Returns:
        {"ok": True, "yaml": "..."} on success
        {"ok": False, "error": "unknown type", "available": [...]} otherwise
    """
    fixture = _EXAMPLES_DIR / f"{diagram_type}_minimal.yaml"
    if not fixture.exists():
        return {
            "ok": False,
            "error": f"unknown diagram type {diagram_type!r}",
            "available": sorted(_TYPE_DOCS.keys()),
        }
    return {"ok": True, "yaml": fixture.read_text(encoding="utf-8")}


def _console_main() -> None:
    """Console-script entry point for ``irtool-mcp``."""
    mcp.run()
