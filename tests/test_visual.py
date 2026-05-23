"""Visual regression tests.

For every fixture under ``tests/ir/valid/``:

1. Build the IR to drawio XML.
2. Render to PNG via the export server.
3. Pixel-diff against the committed golden in ``tests/visual/golden/``.
4. On mismatch, write a diff PNG to ``tests/visual/diff/`` and fail.

The whole module is skipped if the export server is not running, so the
existing unit-test workflow keeps working without it.

Updating goldens
----------------
Set ``IRTOOL_UPDATE_GOLDENS=1`` to overwrite any committed golden with the
freshly rendered output. Use this after intentional layout changes; review
the resulting diff in your VCS before committing.

Tolerance
---------
- Per pixel: any channel differs by more than ``_CHANNEL_TOLERANCE``.
- Per image: fail if more than ``_PIXEL_FRACTION_THRESHOLD`` of pixels
  exceed the per-pixel tolerance. This absorbs sub-pixel anti-aliasing
  noise while still catching real layout drift.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from irtool.build import ir_to_xml
from irtool.models import IR
from irtool.render import Renderer


_VALID_DIR = Path(__file__).parent / "ir" / "valid"
_GOLDEN_DIR = Path(__file__).parent / "visual" / "golden"
_DIFF_DIR = Path(__file__).parent / "visual" / "diff"

_VALID = sorted(_VALID_DIR.glob("*.yaml"))

_UPDATE = os.environ.get("IRTOOL_UPDATE_GOLDENS") == "1"
_CHANNEL_TOLERANCE = 12  # 0–255; sub-pixel AA noise lives below ~10
_PIXEL_FRACTION_THRESHOLD = 0.005  # 0.5% of pixels may legitimately differ


PIL = pytest.importorskip("PIL")
from PIL import Image, ImageChops  # noqa: E402


def _pick_renderer() -> Renderer:
    """Honour DRAWIO_EXPORT_URL if set; otherwise probe the local-server
    port that scripts/start_export_server.ps1 uses (8005) before falling
    back to the upstream default."""
    if "DRAWIO_EXPORT_URL" in os.environ:
        return Renderer()
    for url in ("http://localhost:8005", "http://localhost:8000"):
        r = Renderer(endpoint=url)
        if r.health():
            return r
    return Renderer()  # last resort — caller will check health() again


_renderer = _pick_renderer()
if not _renderer.health():
    pytest.skip(
        f"export server unavailable at {_renderer.endpoint} — set "
        "DRAWIO_EXPORT_URL or start the server to run visual tests",
        allow_module_level=True,
    )


def _load_ir(path: Path) -> IR:
    return IR.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _render(path: Path) -> bytes:
    return _renderer.render_png(ir_to_xml(_load_ir(path)))


def _diff_fraction(a: Image.Image, b: Image.Image) -> tuple[float, Image.Image]:
    """Fraction of pixels that differ by more than the channel tolerance,
    plus a visual diff highlighting them in red."""
    a = a.convert("RGB")
    b = b.convert("RGB")
    diff = ImageChops.difference(a, b)
    bands = diff.split()
    mask = bands[0].point(lambda v: 255 if v > _CHANNEL_TOLERANCE else 0)
    for band in bands[1:]:
        mask_b = band.point(lambda v: 255 if v > _CHANNEL_TOLERANCE else 0)
        mask = ImageChops.lighter(mask, mask_b)
    # Histogram bucket 255 = count of "differing" pixels — avoids the
    # deprecated getdata() iteration.
    differing = mask.histogram()[255]
    total = a.width * a.height
    overlay = Image.new("RGB", a.size, (255, 0, 0))
    visual = Image.composite(overlay, a, mask)
    return differing / total, visual


@pytest.mark.parametrize("path", _VALID, ids=lambda p: p.name)
def test_render_matches_golden(path: Path) -> None:
    golden_path = _GOLDEN_DIR / f"{path.stem}.png"
    fresh_bytes = _render(path)

    if _UPDATE or not golden_path.exists():
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_bytes(fresh_bytes)
        if not _UPDATE:
            pytest.skip(f"golden created for {path.name}; rerun to verify")
        return

    # Compare.
    from io import BytesIO
    fresh = Image.open(BytesIO(fresh_bytes))
    golden = Image.open(golden_path)

    if fresh.size != golden.size:
        _DIFF_DIR.mkdir(parents=True, exist_ok=True)
        fresh.save(_DIFF_DIR / f"{path.stem}.fresh.png")
        pytest.fail(
            f"{path.name}: size changed {golden.size} -> {fresh.size}. "
            f"Fresh render saved to {_DIFF_DIR / f'{path.stem}.fresh.png'}. "
            f"If intentional, rerun with IRTOOL_UPDATE_GOLDENS=1."
        )

    fraction, visual = _diff_fraction(fresh, golden)
    if fraction > _PIXEL_FRACTION_THRESHOLD:
        _DIFF_DIR.mkdir(parents=True, exist_ok=True)
        visual.save(_DIFF_DIR / f"{path.stem}.diff.png")
        fresh.save(_DIFF_DIR / f"{path.stem}.fresh.png")
        pytest.fail(
            f"{path.name}: {fraction:.2%} of pixels differ (threshold "
            f"{_PIXEL_FRACTION_THRESHOLD:.2%}). Diff saved to "
            f"{_DIFF_DIR / f'{path.stem}.diff.png'}. If intentional, "
            f"rerun with IRTOOL_UPDATE_GOLDENS=1."
        )
