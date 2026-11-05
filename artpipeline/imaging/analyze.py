"""Objective checks on a processed image. Ported from the skill's check_asset.py (same sampling,
thresholds and metrics), plus a greyscale-read check the skill describes but never computed."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

from PIL import Image

from artpipeline.imaging.color import (
    contrast_ratio, delta_e, hex_to_rgb, luminance, rgb_to_hex, rgb_to_lab,
)

HALO_FAIL, HALO_WARN = 0.25, 0.12


@dataclass
class Findings:
    fail: list[str] = field(default_factory=list)
    warn: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.fail


@dataclass
class CheckOptions:
    size: tuple[int, int] | None = None
    alpha: str = "any"                 # required | forbidden | any
    halo: bool = True
    palette: list[str] = field(default_factory=list)
    palette_min_share: float | None = 0.85
    palette_max_de: float = 12.0
    backgrounds: list[str] = field(default_factory=list)
    min_contrast: float | None = 1.6
    greyscale_read: bool = True


def _sample(img: Image.Image, step: int) -> Iterator[tuple[int, int, int, int]]:
    px = img.load()
    w, h = img.size
    for y in range(0, h, step):
        for x in range(0, w, step):
            yield px[x, y]


def _halo_ratio(img: Image.Image, step: int, radius: int = 2) -> float:
    """Share of semi-transparent edge pixels whose tone is far (> 0.35 luminance) from the opaque
    pixels right next to them: the signature of a matte fringe left by background removal.

    The skill's check_asset.py compares edge pixels with the asset's *global* mean instead, which
    fails any light asset with a dark keyline (its anti-aliased outline is far from the mean).
    Comparing locally keeps real fringes and drops that false positive."""
    px = img.load()
    w, h = img.size
    considered = fringe = 0
    for y in range(0, h, step):
        for x in range(0, w, step):
            r, g, b, a = px[x, y]
            if not 10 < a < 250:
                continue
            best = None
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h:
                        q = px[nx, ny]
                        if q[3] >= 250:
                            d = abs(luminance(q[:3]) - luminance((r, g, b)))
                            best = d if best is None else min(best, d)
            if best is not None:
                considered += 1
                fringe += best > 0.35
    return fringe / considered if considered else 0.0


def analyze(img: Image.Image, o: CheckOptions) -> Findings:
    img = img.convert("RGBA")
    f = Findings()
    w, h = img.size
    f.metrics["size"] = f"{w}x{h}"
    step = max(1, int(((w * h) / 250_000) ** 0.5))  # sample ~250k pixels max (as the skill does)

    if o.size and (w, h) != tuple(o.size):
        f.fail.append(f"size {w}x{h} != {o.size[0]}x{o.size[1]}")

    alpha = img.getchannel("A")
    amin, _ = alpha.getextrema()
    has_alpha = amin < 255
    corners = [alpha.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    f.metrics["alpha"] = {"has_transparency": has_alpha, "corner_alpha": corners}
    if o.alpha == "required" and (not has_alpha or max(corners) > 10):
        f.fail.append("transparent background required (corners are not transparent)")
    if o.alpha == "forbidden" and has_alpha:
        f.fail.append("must be fully opaque (no alpha allowed for this class)")

    opaque, semi = [], []
    for p in _sample(img, step):
        if p[3] >= 250:
            opaque.append(p[:3])
        elif 10 < p[3] < 250:
            semi.append(p[:3])
    if opaque:
        mean = tuple(sum(c[i] for c in opaque) / len(opaque) for i in range(3))
        f.metrics["mean_rgb"] = rgb_to_hex(mean)
    else:
        mean = (0.0, 0.0, 0.0)
        f.warn.append("no opaque pixels")

    if o.halo and has_alpha and semi and opaque:
        ratio = _halo_ratio(img, step)
        f.metrics["halo_ratio"] = round(ratio, 3)
        if ratio > HALO_FAIL:
            f.fail.append(f"likely matte halo: {ratio:.0%} of edge pixels far from interior tone")
        elif ratio > HALO_WARN:
            f.warn.append(f"possible halo: {ratio:.0%} of edge pixels off-tone")

    if o.palette and opaque and o.palette_min_share is not None:
        pal_lab = [rgb_to_lab(hex_to_rgb(c)) for c in o.palette]
        hits, worst = 0, 0.0
        for c in opaque:
            lab = rgb_to_lab(c)
            de = min(delta_e(lab, p) for p in pal_lab)
            worst = max(worst, de)
            hits += de <= o.palette_max_de
        share = hits / len(opaque)
        f.metrics["palette"] = {"in_palette_share": round(share, 3), "worst_de": round(worst, 1)}
        if share < o.palette_min_share:
            f.fail.append(f"only {share:.0%} of pixels within dE {o.palette_max_de:g} of the palette "
                          f"(need {o.palette_min_share:.0%}); clamp the palette or regenerate")

    if o.backgrounds and opaque:
        f.metrics["contrast"] = {}
        for bg_hex in o.backgrounds:
            bg = hex_to_rgb(bg_hex)
            cr = contrast_ratio(mean, bg)
            f.metrics["contrast"][rgb_to_hex(bg)] = round(cr, 2)
            if o.min_contrast is not None and cr < o.min_contrast:
                f.warn.append(f"low mean contrast {cr:.2f}:1 vs {rgb_to_hex(bg)}; check the silhouette "
                              "and rim on the contact sheet")

    if o.greyscale_read and len(opaque) >= 16:
        labs = sorted((rgb_to_lab(c) for c in opaque), key=lambda v: v[0])
        n = len(labs)
        l_range = labs[int(n * 0.9) - 1][0] - labs[int(n * 0.1)][0]
        a_vals = sorted(v[1] for v in labs)
        b_vals = sorted(v[2] for v in labs)
        chroma_spread = max(a_vals[int(n * 0.9) - 1] - a_vals[int(n * 0.1)],
                            b_vals[int(n * 0.9) - 1] - b_vals[int(n * 0.1)])
        f.metrics["greyscale"] = {"lightness_range": round(l_range, 1), "hue_spread": round(chroma_spread, 1)}
        if chroma_spread > 25 and l_range < 10:
            f.warn.append(f"colours differ mostly in hue (lightness range {l_range:.0f}); "
                          "details may vanish in greyscale or for colour-blind players")
    return f
