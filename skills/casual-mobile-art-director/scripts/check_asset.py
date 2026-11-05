#!/usr/bin/env python3
"""Objective checks for one or more generated assets. Prints JSON (one object per asset) and
exits non-zero if any hard check fails, so it can gate a generate -> check -> fix loop.

  python3 check_asset.py asset.png [more...] \
      [--palette "#22B8B0,#F2C14E,..." | --palette palette.txt] [--max-de 12] [--min-in-palette 0.9] \
      [--bg "#23282B,#49606B"] [--min-contrast 3.0] [--expect-alpha] [--no-alpha] \
      [--size 1024x1024] [--square]

Checks:
  size / square          exact pixel dimensions
  alpha                  --expect-alpha: has real transparency and transparent corners (sprites)
                         --no-alpha: fully opaque (App Store icon, screenshots, Game Center art)
  halo                   share of semi-transparent edge pixels much lighter/darker than the asset
                         interior (matte fringing left by background removal)
  palette                share of opaque pixels within --max-de (CIE76) of a palette colour
  contrast               asset's mean colour vs each background (WCAG ratio) and greyscale
                         separation, a proxy for "reads against the real game backgrounds"
"""
import argparse
import json
import sys

from PIL import Image

from _common import contrast_ratio, delta_e, hex_to_rgb, load_image, luminance, parse_palette, rgb_to_lab


def sample(img, step):
    px = img.load()
    w, h = img.size
    for y in range(0, h, step):
        for x in range(0, w, step):
            yield x, y, px[x, y]


def check(path, a, palette_lab, bgs):
    img = load_image(path)
    w, h = img.size
    res = {"file": path, "size": f"{w}x{h}", "fail": [], "warn": []}
    step = max(1, int(((w * h) / 250_000) ** 0.5))  # sample ~250k pixels max

    if a.size and res["size"] != a.size:
        res["fail"].append(f"size {res['size']} != {a.size}")
    if a.square and w != h:
        res["fail"].append("not square")

    alpha = img.getchannel("A")
    amin, amax = alpha.getextrema()
    has_alpha = amin < 255
    corners = [alpha.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    res["alpha"] = {"has_transparency": has_alpha, "corner_alpha": corners}
    if a.expect_alpha and (not has_alpha or max(corners) > 10):
        res["fail"].append("expected transparent background (corners not transparent)")
    if a.no_alpha and has_alpha:
        res["fail"].append("must be fully opaque (App Store / Game Center art has no alpha)")

    opaque, semi = [], []
    for x, y, p in sample(img, step):
        if p[3] >= 250:
            opaque.append(p[:3])
        elif 10 < p[3] < 250:
            semi.append(p[:3])
    if opaque:
        mean = tuple(sum(c[i] for c in opaque) / len(opaque) for i in range(3))
        res["mean_rgb"] = "#%02X%02X%02X" % tuple(int(v) for v in mean)
    else:
        mean = (0, 0, 0)
        res["warn"].append("no opaque pixels")

    if has_alpha and semi and opaque:
        lum_in = luminance(mean)
        fringe = sum(1 for c in semi if abs(luminance(c) - lum_in) > 0.35)
        ratio = fringe / len(semi)
        res["halo_ratio"] = round(ratio, 3)
        if ratio > 0.25:
            res["fail"].append(f"likely matte halo: {ratio:.0%} of edge pixels far from interior tone")
        elif ratio > 0.12:
            res["warn"].append(f"possible halo: {ratio:.0%} of edge pixels off-tone")

    if palette_lab and opaque:
        hits = 0
        worst = 0.0
        for c in opaque:
            lab = rgb_to_lab(c)
            de = min(delta_e(lab, p) for p in palette_lab)
            worst = max(worst, de)
            hits += de <= a.max_de
        share = hits / len(opaque)
        res["palette"] = {"in_palette_share": round(share, 3), "worst_de": round(worst, 1)}
        if share < a.min_in_palette:
            res["fail"].append(f"only {share:.0%} of pixels within dE {a.max_de} of the palette "
                               f"(need {a.min_in_palette:.0%}); clamp with palette_clamp.py or regenerate")

    if bgs and opaque:
        res["contrast"] = {}
        for bg in bgs:
            cr = contrast_ratio(mean, bg)
            res["contrast"]["#%02X%02X%02X" % bg] = round(cr, 2)
            if cr < a.min_contrast:
                res["warn"].append(f"low mean contrast {cr:.2f}:1 vs #%02X%02X%02X; check the silhouette "
                                   f"and rim on the contact sheet" % bg)
    res["pass"] = not res["fail"]
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("assets", nargs="+")
    ap.add_argument("--palette")
    ap.add_argument("--max-de", type=float, default=12.0)
    ap.add_argument("--min-in-palette", type=float, default=0.85)
    ap.add_argument("--bg", default="")
    ap.add_argument("--min-contrast", type=float, default=1.6)
    ap.add_argument("--expect-alpha", action="store_true")
    ap.add_argument("--no-alpha", action="store_true")
    ap.add_argument("--size")
    ap.add_argument("--square", action="store_true")
    a = ap.parse_args()
    pal = [rgb_to_lab(c) for c in parse_palette(a.palette)] if a.palette else []
    bgs = [hex_to_rgb(h) for h in a.bg.split(",") if h.strip()]
    results = [check(p, a, pal, bgs) for p in a.assets]
    print(json.dumps(results, indent=2))
    sys.exit(0 if all(r["pass"] for r in results) else 1)


if __name__ == "__main__":
    main()
