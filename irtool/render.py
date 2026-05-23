"""End-to-end renderer client for drawio XML -> PNG.

Talks to a `drawio-image-export2` server (https://github.com/jgraph/drawio-image-export2),
which is the same headless-Chrome + drawio renderer jgraph uses for export.draw.io.

The server can be hosted in three ways:

    # Docker (recommended)
    docker run -d -p 8000:8000 --name drawio-export jgraph/export-server

    # Node (no docker needed)
    git clone https://github.com/jgraph/drawio-image-export2
    cd drawio-image-export2 && npm install && npm start

    # Hosted (rate-limited, no setup)
    export DRAWIO_EXPORT_URL=https://exp.draw.io/ImageExport4/export

The client picks up DRAWIO_EXPORT_URL from the environment, defaulting to
http://localhost:8005 (the port used by scripts/start_export_server.ps1).
"""

from __future__ import annotations

import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


DEFAULT_ENDPOINT = os.environ.get("DRAWIO_EXPORT_URL", "http://localhost:8005")


class RenderError(RuntimeError):
    """Raised when the export server is unreachable or returns an error."""


class Renderer:
    def __init__(self, endpoint: str = DEFAULT_ENDPOINT, timeout: float = 30.0):
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout

    def health(self) -> bool:
        """True if the export server is reachable.

        The server returns HTTP errors for empty GETs (it expects xml/url
        params), so any HTTP response — including a 4xx — proves the
        process is up. Only connection-level failures count as unhealthy.
        """
        try:
            req = urllib.request.Request(self.endpoint, method="GET")
            with urllib.request.urlopen(req, timeout=5):
                return True
        except urllib.error.HTTPError:
            return True
        except (urllib.error.URLError, OSError, TimeoutError):
            return False

    def render_png(self, drawio_xml: str, *, scale: float = 1.0) -> bytes:
        """Render drawio XML to PNG bytes."""
        form = urllib.parse.urlencode(
            {"xml": drawio_xml, "format": "png", "scale": str(scale)}
        ).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=form,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status != 200:
                    raise RenderError(
                        f"export server returned HTTP {resp.status}"
                    )
                body = resp.read()
        except urllib.error.URLError as e:
            raise RenderError(f"could not reach {self.endpoint}: {e}") from e

        if len(body) < 200 or not body.startswith(b"\x89PNG"):
            preview = body[:80].decode("utf-8", errors="replace")
            raise RenderError(
                f"response is not a PNG ({len(body)} bytes). "
                f"head: {preview!r}"
            )
        return body

    def render_file(
        self,
        drawio_path: str | Path,
        png_path: str | Path,
        *,
        scale: float = 1.0,
    ) -> Path:
        drawio_path = Path(drawio_path)
        png_path = Path(png_path)
        xml = drawio_path.read_text(encoding="utf-8")
        png_bytes = self.render_png(xml, scale=scale)
        png_path.write_bytes(png_bytes)
        return png_path
