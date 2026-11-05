#!/usr/bin/env python3
"""Snap every pixel of a generated raster to the nearest brief palette colour (CIELAB),
keeping alpha. Removes the off-palette drift image models introduce.

  python3 palette_clamp.py in.png out.png --palette "#22B8B0,#F2C14E,#1C1413" [--soft 0.0-1.0]

--soft blends the snapped colour with the original (0 = hard posterise, default; 0.3 keeps some
shading). Hard clamp suits flat/vector/pixel styles; use --soft for painterly ones.
"""
import argparse

from PIL import Image

from _common import delta_e, load_image, parse_palette, rgb_to_lab


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--palette", required=True)
    ap.add_argument("--soft", type=float, default=0.0)
    a = ap.parse_args()

    pal = parse_palette(a.palette)
    pal_lab = [rgb_to_lab(c) for c in pal]
    img = load_image(a.src)
    px = img.load()
    cache = {}
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, al = px[x, y]
            if al == 0:
                continue
            key = (r >> 2, g >> 2, b >> 2)
            if key not in cache:
                lab = rgb_to_lab((r, g, b))
                cache[key] = pal[min(range(len(pal)), key=lambda i: delta_e(lab, pal_lab[i]))]
            nr, ng, nb = cache[key]
            if a.soft:
                s = a.soft
                nr, ng, nb = (int(nr * (1 - s) + r * s), int(ng * (1 - s) + g * s), int(nb * (1 - s) + b * s))
            px[x, y] = (nr, ng, nb, al)
    img.save(a.dst)
    print(f"wrote {a.dst} ({len(pal)}-colour palette, soft={a.soft})")


if __name__ == "__main__":
    main()
