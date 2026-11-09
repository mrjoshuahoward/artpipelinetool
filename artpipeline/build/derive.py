"""The `derive` recipe compiler (2.1 B3): approved assets → one sprite sheet or texture atlas.

Frames are other assets' approved outputs, in the order the brief lists them. The canvas is the
asset's class master (engines want fixed, usually power-of-two, texture sizes), so the usual size,
alpha and palette checks apply to the sheet as a whole.

* `layout: grid` — a sprite sheet: every frame centred in an equal cell, row by row. Animation strips.
* `layout: pack` — a texture atlas: frames (trimmed of transparent borders by default) packed onto
  shelves, tallest first. UI sets, icons, mixed-size sprites.

The frame rectangles (plus trim offsets and the optional animation) are part of the build record;
`place` turns them into Phaser atlas JSON, Godot AtlasTexture/SpriteFrames resources or an Xcode
.spriteatlas. The fingerprint hashes the pixels and the frame table, not the PNG encoding."""
from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from artpipeline.build.svg import BuildError, Compiled
from artpipeline.imaging.render import RenderError, load_rgba

BUILDER_VERSION = "derive-1"

AssetResolver = Callable[[str], Path]


def _frame(p: Path, aid: str, cell: tuple[int, int] | None, pixel_art: bool) -> Image.Image:
    try:
        img = load_rgba(p, cell or (1024, 1024))
    except RenderError as e:
        raise BuildError(f"frame '{aid}': {e}") from None
    if cell and img.size != cell:
        w, h = img.size
        s = min(cell[0] / w, cell[1] / h)
        size = (max(1, round(w * s)), max(1, round(h * s)))
        if pixel_art and (s < 1 or abs(s - round(s)) > 1e-9):
            raise BuildError(f"frame '{aid}': pixel art scales only by whole numbers "
                             f"({w}x{h} → cell {cell[0]}x{cell[1]})")
        img = img.resize(size, Image.Resampling.NEAREST if pixel_art else Image.Resampling.LANCZOS)
    return img


def _extrude(sheet: Image.Image, img: Image.Image, x: int, y: int, n: int) -> None:
    """Repeat the frame's edge pixels n px outward (corners included) so texture filtering never
    samples a neighbouring frame or the transparent gap."""
    w, h = img.size
    top, bottom = img.crop((0, 0, w, 1)), img.crop((0, h - 1, w, h))
    left, right = img.crop((0, 0, 1, h)), img.crop((w - 1, 0, w, h))
    for k in range(1, n + 1):
        sheet.paste(top, (x, y - k))
        sheet.paste(bottom, (x, y + h - 1 + k))
        sheet.paste(left, (x - k, y))
        sheet.paste(right, (x + w - 1 + k, y))
    for (cx, cy), corner in (((x - n, y - n), (0, 0)), ((x + w, y - n), (w - 1, 0)),
                             ((x - n, y + h), (0, h - 1)), ((x + w, y + h), (w - 1, h - 1))):
        sheet.paste(Image.new("RGBA", (n, n), img.getpixel(corner)), (cx, cy))


def compile_derive(
    root: Path,
    *,
    frames: list[str],
    layout: str,
    cell: tuple[int, int] | None,
    columns: int | None,
    padding: int,
    extrude: int,
    trim: bool | None,
    animation: dict[str, Any] | None,
    asset: dict[str, Any],
    master: tuple[int, int],
    pixel_art: bool = False,
    assets: AssetResolver | None = None,
) -> Compiled:
    if not frames:
        raise BuildError("a derive recipe needs frames (asset ids) or frames_group")
    if assets is None:
        raise BuildError("derive recipes need the pipeline (no resolver)")
    if asset.get("id") in frames:
        raise BuildError("an asset can't be a frame of itself")
    trim = (layout == "pack") if trim is None else trim
    inputs: dict[str, str] = {}
    imgs: list[tuple[str, Image.Image, tuple[int, int], tuple[int, int]]] = []  # id, img, source size, trim off
    for aid in frames:
        p = assets(aid)  # BuildError when it isn't approved
        inputs[f"asset:{aid}"] = hashlib.sha256(p.read_bytes()).hexdigest()
        if p.suffix.lower() == ".svg" and not cell:
            raise BuildError(f"frame '{aid}' is a vector; set cell: [w, h] to say what size to draw it")
        img = _frame(p, aid, cell, pixel_art)
        src_size = img.size
        off = (0, 0)
        if trim:
            bbox = img.getchannel("A").getbbox()
            if bbox is None:
                raise BuildError(f"frame '{aid}' is fully transparent")
            off = (bbox[0], bbox[1])
            img = img.crop(bbox)
        imgs.append((aid, img, src_size, off))

    W, H = master
    gap = padding + 2 * extrude
    rects: dict[str, tuple[int, int]] = {}
    if layout == "grid":
        cw = cell[0] if cell else max(s[0] for _, _, s, _ in imgs)
        ch = cell[1] if cell else max(s[1] for _, _, s, _ in imgs)
        cols = columns or max(1, min(len(imgs), (W - extrude + padding) // (cw + gap) if cw + gap else 1))
        rows = math.ceil(len(imgs) / cols)
        need = (cols * cw + (cols - 1) * gap + 2 * extrude, rows * ch + (rows - 1) * gap + 2 * extrude)
        if need[0] > W or need[1] > H:
            raise BuildError(f"{len(imgs)} frames of {cw}x{ch} in {cols} columns need {need[0]}x{need[1]}; "
                             f"the class master is {W}x{H}. Raise the master (overrides: {{master: [..]}}), "
                             "shrink the cell or change columns")
        for i, (aid, img, src, off) in enumerate(imgs):
            cx = extrude + (i % cols) * (cw + gap)
            cy = extrude + (i // cols) * (ch + gap)
            # centre the (untrimmed) frame in its cell; a trimmed frame keeps its offset
            ox = (cw - src[0]) // 2 + off[0]
            oy = (ch - src[1]) // 2 + off[1]
            rects[aid] = (cx + ox, cy + oy)
        cell_size = (cw, ch)
    elif layout == "pack":
        order = sorted(range(len(imgs)), key=lambda i: (-imgs[i][1].size[1], -imgs[i][1].size[0], imgs[i][0]))
        x = y = extrude
        shelf_h = 0
        for i in order:
            aid, img, _, _ = imgs[i]
            w, h = img.size
            if x + w + extrude > W:
                x, y = extrude, y + shelf_h + gap
                shelf_h = 0
            if x + w + extrude > W or y + h + extrude > H:
                raise BuildError(f"the frames don't fit in {W}x{H} (stopped at '{aid}', {w}x{h}). Raise the "
                                 "class master, set a smaller cell, or split the atlas")
            rects[aid] = (x, y)
            x += w + gap
            shelf_h = max(shelf_h, h)
        cell_size = None
    else:
        raise BuildError(f"layout must be grid or pack, not '{layout}'")

    sheet = Image.new("RGBA", master, (0, 0, 0, 0))
    table: dict[str, dict[str, int]] = {}
    for aid, img, src, off in imgs:
        x, y = rects[aid]
        sheet.paste(img, (x, y))
        if extrude:
            _extrude(sheet, img, x, y, extrude)
        w, h = img.size
        table[aid] = {"x": x, "y": y, "w": w, "h": h, "source_w": src[0], "source_h": src[1],
                      "trim_x": off[0], "trim_y": off[1]}

    atlas: dict[str, Any] = {"layout": layout, "size": [W, H], "frames": table, "order": list(frames)}
    if cell_size:
        atlas["cell"] = list(cell_size)
    if animation:
        atlas["animation"] = {"fps": float(animation.get("fps", 12)), "loop": bool(animation.get("loop", True)),
                              "sequence": list(animation.get("sequence") or frames)}

    buf = io.BytesIO()
    sheet.save(buf, format="PNG", optimize=False, compress_level=6)
    h = hashlib.sha256(BUILDER_VERSION.encode() + b"\n")
    h.update(sheet.tobytes())
    h.update(json.dumps(atlas, sort_keys=True).encode())
    params = {"layout": layout, "padding": str(padding), "extrude": str(extrude), "trim": str(trim).lower()}
    if cell:
        params["cell"] = f"{cell[0]}x{cell[1]}"
    if columns:
        params["columns"] = str(columns)
    return Compiled(svg=buf.getvalue(), fingerprint=h.hexdigest(), inputs=dict(sorted(inputs.items())),
                    tokens={}, params=params, kind="derive", builder=BUILDER_VERSION, ext=".png", atlas=atlas)
