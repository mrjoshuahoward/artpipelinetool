"""Contact sheets: each asset at its true display sizes on its real backgrounds, plus a greyscale
row. Ported from the skill's contact_sheet.py with three fixes: non-square art keeps its aspect,
pixel art scales nearest-neighbour, and each asset uses its own sizes/backgrounds so mixed
classes can share a sheet. Large sets paginate."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from artpipeline.imaging.color import hex_to_rgb

PAD = 16
MARGIN = 14  # background shown around every tile, so opaque art is judged against it too
LABEL_W = 190
DEFAULT_SIZES = [256, 64]
DEFAULT_BGS = ["#1C1C1E", "#F2F2F7"]
SHEET_BG = (236, 236, 240)
PER_PAGE = 12


@dataclass
class SheetItem:
    label: str
    image: Image.Image                 # RGBA, at least as large as the biggest display size
    sizes: list[int] = field(default_factory=list)
    backgrounds: list[str] = field(default_factory=list)
    sublabel: str = ""
    pixel_art: bool = False
    icon_mask: bool = False


def _font(size: int):
    for f in ("/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def _fit(img: Image.Image, box: int, pixel_art: bool) -> Image.Image:
    w, h = img.size
    s = box / max(w, h)
    size = (max(1, round(w * s)), max(1, round(h * s)))
    return img.resize(size, Image.Resampling.NEAREST if pixel_art else Image.Resampling.LANCZOS)


def _rounded(img: Image.Image, ratio: float = 0.225) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.size[0] - 1, img.size[1] - 1],
                                           radius=int(min(img.size) * ratio), fill=255)
    out = img.copy()
    out.putalpha(Image.composite(img.getchannel("A"), mask, mask))
    return out


def _grey(img: Image.Image) -> Image.Image:
    g = ImageOps.grayscale(img.convert("RGB")).convert("RGBA")
    g.putalpha(img.getchannel("A"))
    return g


def render_page(items: list[SheetItem], title: str = "") -> Image.Image:
    rows = []
    for it in items:
        sizes = it.sizes or DEFAULT_SIZES
        bgs = it.backgrounds or DEFAULT_BGS
        cell_h = max(sizes) + 2 * MARGIN + PAD
        width = LABEL_W + sum(s + 2 * MARGIN + PAD for s in sizes) * len(bgs) + PAD
        rows.append((it, sizes, bgs, cell_h, width))
    header = 44 if title else 12
    W = max(r[4] for r in rows)
    H = header + sum(2 * r[3] + 20 for r in rows) + PAD
    sheet = Image.new("RGB", (W, H), SHEET_BG)
    d = ImageDraw.Draw(sheet)
    f, fs = _font(14), _font(11)
    if title:
        d.text((PAD, 14), title, fill=(30, 30, 30), font=_font(16))

    y = header
    for it, sizes, bgs, cell_h, _ in rows:
        d.text((PAD, y), "  ".join(f"{s}px" for s in sizes) + "  on  " + ", ".join(bgs),
               fill=(110, 110, 110), font=fs)
        y += 16
        for variant, fn in (("colour", lambda i: i), ("greyscale", _grey)):
            d.text((PAD, y + 6), it.label, fill=(20, 20, 20), font=f)
            d.text((PAD, y + 26), variant, fill=(90, 90, 90), font=fs)
            if it.sublabel and variant == "colour":
                d.text((PAD, y + 42), it.sublabel, fill=(90, 90, 90), font=fs)
            src = fn(it.image)
            x = LABEL_W
            box_h = max(sizes) + 2 * MARGIN
            for bg in bgs:
                for s in sizes:
                    sheet.paste(hex_to_rgb(bg), (x, y, x + s + 2 * MARGIN, y + box_h))
                    t = _fit(src, s, it.pixel_art)
                    if it.icon_mask:
                        t = _rounded(t)
                    ox = x + MARGIN + (s - t.size[0]) // 2
                    oy = y + (box_h - t.size[1]) // 2
                    sheet.paste(t, (ox, oy), t)
                    x += s + 2 * MARGIN + PAD
            y += cell_h
        y += 4
    return sheet


def build_sheets(items: list[SheetItem], out_dir: Path, stem: str, title: str = "") -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = [items[i:i + PER_PAGE] for i in range(0, len(items), PER_PAGE)] or [[]]
    paths = []
    for k, page in enumerate(pages, 1):
        if not page:
            break
        t = f"{title}  (page {k}/{len(pages)})" if title and len(pages) > 1 else title
        p = out_dir / (f"{stem}.png" if len(pages) == 1 else f"{stem}-p{k}.png")
        render_page(page, t).save(p)
        paths.append(p)
    return paths


# ---------------------------------------------------------------- overview grid

GRID_MAX_EDGE = 1568  # stay under the client's inline downscale limit so tiles stay at true size
GRID_LABEL_H = 18
GRID_MAX_TILE = 256   # atlases and screenshots display larger than a grid can hold
GRID_SMALL_TILE = 128  # bigger tiles are paginated apart from icons and sprites


def _grid_cell(it: SheetItem, size: int) -> tuple[int, int]:
    bgs = it.backgrounds or DEFAULT_BGS
    tile = size + 2 * MARGIN
    return tile * len(bgs) * 2 + 6, tile + GRID_LABEL_H  # colour + greyscale per background


def _grid_size(it: SheetItem) -> int:
    """The tile size in the grid: the smallest display size, capped so one row of the asset still fits
    a page (atlases and screenshots display far larger than a grid can show; their strips show them)."""
    bgs = len(it.backgrounds or DEFAULT_BGS)
    fits = (GRID_MAX_EDGE - 2 * PAD - 6) // (2 * bgs) - 2 * MARGIN
    return min(min(it.sizes or DEFAULT_SIZES), GRID_MAX_TILE, fits)


def render_grid_pages(items: list[SheetItem], title: str = "") -> list[Image.Image]:
    """Many assets per image, each at its smallest real display size (capped at GRID_MAX_TILE) on every
    background, in colour and greyscale. Pages stay within GRID_MAX_EDGE so the model sees them
    unscaled. Large tiles get their own pages, so one atlas doesn't blow up the cells of every icon."""
    if not items:
        return []
    header = 34 if title else 8
    chunks: list[tuple[list[SheetItem], int, int, int]] = []
    small = [it for it in items if _grid_size(it) <= GRID_SMALL_TILE]
    large = [it for it in items if _grid_size(it) > GRID_SMALL_TILE]
    for group in (small, large):
        if not group:
            continue
        cw = max(_grid_cell(it, _grid_size(it))[0] for it in group) + PAD
        ch = max(_grid_cell(it, _grid_size(it))[1] for it in group) + 8
        cols = max(1, (GRID_MAX_EDGE - PAD) // cw)
        per_page = cols * max(1, (GRID_MAX_EDGE - header - PAD) // ch)
        chunks += [(group[i:i + per_page], cw, ch, cols) for i in range(0, len(group), per_page)]
    f, fs = _font(12), _font(11)
    pages = []
    for k, (chunk, cw, ch, cols) in enumerate(chunks, 1):
        n_rows = -(-len(chunk) // cols)
        W = PAD + min(cols, len(chunk)) * cw
        H = header + n_rows * ch + PAD
        sheet = Image.new("RGB", (W, H), SHEET_BG)
        d = ImageDraw.Draw(sheet)
        if title:
            t = f"{title}  (page {k}/{len(chunks)})" if len(chunks) > 1 else title
            d.text((PAD, 10), t, fill=(30, 30, 30), font=_font(14))
        for i, it in enumerate(chunk):
            s = _grid_size(it)
            x0 = PAD + (i % cols) * cw
            y0 = header + (i // cols) * ch
            label = it.label + (f"  ·  {it.sublabel}" if it.sublabel else "")
            if s < min(it.sizes or DEFAULT_SIZES):
                label = f"{label[:40]}  ·  shown at {s}px"
            d.text((x0, y0), label[:60], fill=(20, 20, 20), font=f if not it.sublabel else fs)
            x = x0
            y = y0 + GRID_LABEL_H
            tile = s + 2 * MARGIN
            for fn in (lambda im: im, _grey):
                src = fn(it.image)
                for bg in it.backgrounds or DEFAULT_BGS:
                    sheet.paste(hex_to_rgb(bg), (x, y, x + tile, y + tile))
                    t = _fit(src, s, it.pixel_art)
                    if it.icon_mask:
                        t = _rounded(t)
                    sheet.paste(t, (x + MARGIN + (s - t.size[0]) // 2, y + MARGIN + (s - t.size[1]) // 2), t)
                    x += tile
                x += 6
        pages.append(sheet)
    return pages
