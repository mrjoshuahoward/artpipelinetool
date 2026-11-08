"""Deterministic post-processing: background removal, trim, fit to master, palette clamp,
flatten, renditions. Ported from the skill's palette_clamp.py / export_sizes.py, plus the
chroma-key removal the skill's production loop describes."""
from __future__ import annotations

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from artpipeline.imaging.color import RGB, hex_to_rgb, nearest, rgb_to_lab


class ProcessError(Exception):
    """A processing step refused (e.g. would upscale); reported as a check failure."""


def remove_background(img: Image.Image, t0: int = 24, t1: int = 64) -> Image.Image:
    """Key out a flat background colour (estimated from the border) that is connected to the
    edges, so interior areas of the same colour (white eyes on a white backdrop) survive.
    Channel distance <= t0 becomes transparent; t0..t1 ramps alpha to feather the edge."""
    img = img.convert("RGBA")
    w, h = img.size
    border = _border_pixels(img)
    bg = tuple(sorted(c[i] for c in border)[len(border) // 2] for i in range(3))
    rgb = img.convert("RGB")
    r, g, b = ImageChops.difference(rgb, Image.new("RGB", img.size, bg)).split()
    dist = ImageChops.lighter(ImageChops.lighter(r, g), b)

    near = dist.point(lambda v: 255 if v <= t1 else 0)
    step = max(1, min(w, h) // 32)
    seeds = [(x, 0) for x in range(0, w, step)] + [(x, h - 1) for x in range(0, w, step)]
    seeds += [(0, y) for y in range(0, h, step)] + [(w - 1, y) for y in range(0, h, step)]
    for s in seeds:
        if near.getpixel(s) == 255:
            ImageDraw.floodfill(near, s, 128)
    connected = near.point(lambda v: 255 if v == 128 else 0).filter(ImageFilter.MaxFilter(3))

    span = max(1, t1 - t0)
    ramp = dist.point(lambda v: 0 if v <= t0 else 255 if v >= t1 else int((v - t0) * 255 / span))
    alpha = img.getchannel("A")
    keyed = ImageChops.darker(ramp, alpha)
    img.putalpha(Image.composite(keyed, alpha, connected))
    return img


def trim(img: Image.Image, threshold: int = 10) -> Image.Image:
    bbox = img.getchannel("A").point(lambda v: 255 if v > threshold else 0).getbbox()
    return img.crop(bbox) if bbox else img


def fit_to_master(img: Image.Image, master: tuple[int, int], *, pixel_art: bool, pad: bool) -> Image.Image:
    """Scale a raster to the master size. Never upscales. With pad=True (after trim) the image is
    fitted inside the master canvas, centred on transparency; otherwise aspect must match."""
    mw, mh = master
    w, h = img.size
    if (w, h) == (mw, mh):
        return img
    if pad:
        scale = min(mw / w, mh / h, 1.0)  # never upscale; smaller art is centred as-is
        nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
        res = img if (nw, nh) == (w, h) else img.resize((nw, nh), _resample(pixel_art))
        canvas = Image.new("RGBA", (mw, mh), (0, 0, 0, 0))
        canvas.paste(res, ((mw - nw) // 2, (mh - nh) // 2))
        return canvas
    if abs((w / h) - (mw / mh)) > 0.01 * (mw / mh):
        raise ProcessError(f"aspect {w}x{h} does not match master {mw}x{mh}")
    if w < mw:
        raise ProcessError(f"source {w}x{h} is smaller than master {mw}x{mh}; won't upscale, "
                           "produce it larger")
    if pixel_art and w % mw:
        raise ProcessError(f"pixel art {w}x{h} is not an integer multiple of master {mw}x{mh}")
    return img.resize((mw, mh), _resample(pixel_art))


def palette_clamp(img: Image.Image, palette: list[str], soft: float = 0.0) -> Image.Image:
    """Snap every visible pixel to its nearest palette colour (CIELAB), keeping alpha.
    soft blends back toward the original (0 = hard posterise; ~0.3 for painterly)."""
    pal: list[RGB] = [hex_to_rgb(h) for h in palette]
    pal_lab = [rgb_to_lab(c) for c in pal]
    img = img.convert("RGBA")
    data = bytearray(img.tobytes())
    cache: dict[RGB, RGB] = {}
    for i in range(0, len(data), 4):
        if data[i + 3] == 0:
            continue
        key = (data[i], data[i + 1], data[i + 2])
        n = cache.get(key)
        if n is None:
            n = nearest(key, pal, pal_lab)[0]
            cache[key] = n
        if soft:
            n = tuple(int(n[k] * (1 - soft) + key[k] * soft) for k in range(3))
        data[i:i + 3] = bytes(n)
    return Image.frombytes("RGBA", img.size, bytes(data))


def flatten(img: Image.Image, color: str) -> Image.Image:
    bg = Image.new("RGBA", img.size, hex_to_rgb(color) + (255,))
    return Image.alpha_composite(bg, img.convert("RGBA"))


def resize_rendition(master_img: Image.Image, size: tuple[int, int], *, pixel_art: bool) -> Image.Image:
    mw, mh = master_img.size
    if size[0] > mw or size[1] > mh:
        raise ProcessError(f"rendition {size[0]}x{size[1]} is larger than the {mw}x{mh} raster master; "
                           "won't upscale")
    if pixel_art and (mw % size[0] and size[0] % mw):
        raise ProcessError(f"pixel-art rendition {size[0]}px is not an integer factor of {mw}px")
    return master_img.resize(size, _resample(pixel_art))


def _resample(pixel_art: bool) -> int:
    return Image.Resampling.NEAREST if pixel_art else Image.Resampling.LANCZOS


def _border_pixels(img: Image.Image) -> list[tuple[int, int, int]]:
    w, h = img.size
    px = img.load()
    pts = [(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)]
    pts += [(0, y) for y in range(h)] + [(w - 1, y) for y in range(h)]
    return [px[p][:3] for p in pts[:: max(1, len(pts) // 2000)]]
