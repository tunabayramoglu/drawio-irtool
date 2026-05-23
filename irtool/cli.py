"""Command-line interface for irtool.

Usage:
    python -m irtool check FILE [FILE ...] [--json] [--strict]
    python -m irtool render FILE [--out FILE] [--server URL]

Exit codes:
    0   no errors (warnings allowed unless --strict)
    1   at least one error, or --strict and at least one warning
    2   CLI usage error / file not found
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml
from pydantic import ValidationError

from .build import ir_to_xml
from .issues import Severity
from .models import IR
from .render import RenderError, Renderer
from .validate import summarize, validate_path


# ----------------------------- check -----------------------------


def _print_human(path: Path, issues: list, totals: tuple[int, int]) -> None:
    errs, warns = totals
    if not issues:
        print(f"{path}: OK")
        return
    parts = []
    if errs:
        parts.append(f"{errs} error{'s' if errs != 1 else ''}")
    if warns:
        parts.append(f"{warns} warning{'s' if warns != 1 else ''}")
    print(f"{path}: {', '.join(parts)}")
    for issue in issues:
        print(f"  {issue.format()}")


def _emit_json(per_file: list[dict]) -> None:
    json.dump({"files": per_file}, sys.stdout, indent=2)
    sys.stdout.write("\n")


def cmd_check(args: argparse.Namespace) -> int:
    per_file: list[dict] = []
    overall_failed = False

    for raw in args.paths:
        path = Path(raw)
        if not path.exists():
            issues_dict = [
                {
                    "severity": "error",
                    "code": "file_not_found",
                    "path": str(path),
                    "message": "file does not exist",
                }
            ]
            per_file.append({"path": str(path), "issues": issues_dict})
            overall_failed = True
            if not args.json:
                print(f"{path}: file does not exist", file=sys.stderr)
            continue

        issues = validate_path(path)
        errs, warns = summarize(issues)
        if errs or (args.strict and warns):
            overall_failed = True

        if args.json:
            per_file.append(
                {
                    "path": str(path),
                    "issues": [i.model_dump(mode="json") for i in issues],
                }
            )
        else:
            _print_human(path, issues, (errs, warns))

    if args.json:
        _emit_json(per_file)

    return 1 if overall_failed else 0


# ----------------------------- render -----------------------------


def cmd_render(args: argparse.Namespace) -> int:
    src = Path(args.path)
    if not src.exists():
        print(f"{src}: file does not exist", file=sys.stderr)
        return 2

    out = Path(args.out) if args.out else src.with_suffix(".png")
    renderer = Renderer(endpoint=args.server) if args.server else Renderer()

    try:
        renderer.render_file(src, out, scale=args.scale)
    except RenderError as e:
        print(f"render failed: {e}", file=sys.stderr)
        return 1

    size_kb = out.stat().st_size / 1024
    print(f"{out}  ({size_kb:.1f} KB)")
    return 0


# ------------------------------ build ------------------------------


def cmd_build(args: argparse.Namespace) -> int:
    src = Path(args.path)
    if not src.exists():
        print(f"{src}: file does not exist", file=sys.stderr)
        return 2

    # Validate first so build never sees malformed IR.
    issues = validate_path(src)
    errs, warns = summarize(issues)
    if errs:
        print(f"{src}: refusing to build, {errs} validation error(s):",
              file=sys.stderr)
        for issue in issues:
            if issue.severity == Severity.ERROR:
                print(f"  {issue.format()}", file=sys.stderr)
        return 1
    for issue in issues:
        if issue.severity == Severity.WARNING:
            print(f"  warning: {issue.format()}", file=sys.stderr)

    try:
        data = yaml.safe_load(src.read_text(encoding="utf-8"))
        ir = IR.model_validate(data)
    except (yaml.YAMLError, ValidationError) as e:  # already validated, but be defensive
        print(f"{src}: unexpected parse failure: {e}", file=sys.stderr)
        return 1

    xml = ir_to_xml(ir)
    out = Path(args.out) if args.out else src.with_suffix(".drawio")
    out.write_text(xml, encoding="utf-8")
    print(f"{out}  ({len(xml)} bytes)")

    if args.render:
        png_out = out.with_suffix(".png")
        try:
            renderer = (
                Renderer(endpoint=args.server) if args.server else Renderer()
            )
            renderer.render_file(out, png_out)
            print(f"{png_out}  ({png_out.stat().st_size / 1024:.1f} KB)")
        except RenderError as e:
            print(f"render failed: {e}", file=sys.stderr)
            return 1
    return 0


# ----------------------------- main -----------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="irtool",
        description="IR validation and rendering for drawio diagrams.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    chk = sub.add_parser(
        "check",
        help="Validate one or more IR YAML files (schema + semantic).",
    )
    chk.add_argument("paths", nargs="+", help="YAML files to validate.")
    chk.add_argument(
        "--json", action="store_true", help="Emit JSON instead of human output."
    )
    chk.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on warnings as well as errors.",
    )
    chk.set_defaults(func=cmd_check)

    rnd = sub.add_parser(
        "render",
        help="Render a drawio file to PNG via the export server.",
    )
    rnd.add_argument("path", help="Path to a .drawio file.")
    rnd.add_argument("--out", help="Output PNG path (default: alongside source).")
    rnd.add_argument(
        "--server",
        help="Export server URL (default: DRAWIO_EXPORT_URL env or "
        "http://localhost:8000).",
    )
    rnd.add_argument(
        "--scale", type=float, default=1.0, help="Render scale (default 1.0)."
    )
    rnd.set_defaults(func=cmd_render)

    bld = sub.add_parser(
        "build",
        help="Convert an IR YAML file to a drawio file (validates first).",
    )
    bld.add_argument("path", help="Path to an IR YAML file.")
    bld.add_argument("--out", help="Output .drawio path.")
    bld.add_argument(
        "--render",
        action="store_true",
        help="Also render to PNG via the export server.",
    )
    bld.add_argument(
        "--server",
        help="Export server URL (only used with --render).",
    )
    bld.set_defaults(func=cmd_build)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
