"""Load rasters and render SVGs.

SVG rendering uses resvg (bundled via resvg-py, no system tools). A VectorCraft backend
(`vectorcraft-cli export`) is planned so assets authored in VectorCraft can be checked with
the same engine that drew them; it is not wired up until the CLI is installed and its export
syntax is verified."""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, UnidentifiedImageError


class RenderError(Exception):
    pass


def is_svg(path: Path) -> bool:
    return path.suffix.lower() == ".svg"


def render_svg(path: Path, width: int, height: int | None = None) -> Image.Image:
    import resvg_py

    try:
        data = resvg_py.svg_to_bytes(
            svg_path=str(path), width=int(width), height=int(height or width),
            resources_dir=str(path.parent),
        )
    except ValueError as e:
        raise RenderError(f"SVG did not render: {e}") from e
    img = Image.open(io.BytesIO(bytes(data))).convert("RGBA")
    img.load()
    return img


def load_rgba(path: Path, size: tuple[int, int] | None = None) -> Image.Image:
    """Open a raster as RGBA, or render an SVG at `size` (default 1024 square)."""
    if is_svg(path):
        w, h = size or (1024, 1024)
        return render_svg(path, w, h)
    try:
        with Image.open(path) as im:
            im.load()
            return im.convert("RGBA")
    except (UnidentifiedImageError, OSError) as e:
        raise RenderError(f"not a decodable image: {e}") from e
