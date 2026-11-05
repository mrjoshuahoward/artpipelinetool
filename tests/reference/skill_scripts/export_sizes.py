#!/usr/bin/env python3
"""Export a master asset (PNG or SVG) to the sizes an engine expects.

  # iOS / SpriteKit image set: base point size 44 -> name.png, name@2x.png, name@3x.png
  python3 export_sizes.py master.svg out_dir/ --name coin --points 44 --scales 1,2,3

  # explicit pixel sizes (Phaser @2x-authored atlas frames, Godot, store art)
  python3 export_sizes.py master.png out_dir/ --name badge --px 512,1024

  # pixel art: integer nearest-neighbour scaling only
  python3 export_sizes.py sprite.png out_dir/ --name hero --px 32,64,128 --pixel

  # flatten onto a colour (App Store icon / Game Center art must have no alpha)
  python3 export_sizes.py icon.svg out_dir/ --name AppIcon --px 1024 --flatten "#10202B"

SVG masters are re-rasterised per size (sharper than downscaling). Raster masters downscale with
Lanczos. Never upscale a raster master; the script refuses unless --allow-upscale.
"""
import argparse
import os

from PIL import Image

from _common import hex_to_rgb, load_image


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("master")
    ap.add_argument("out_dir")
    ap.add_argument("--name", required=True)
    ap.add_argument("--points", type=int, help="base size in points (with --scales)")
    ap.add_argument("--scales", default="1,2,3")
    ap.add_argument("--px", help="comma-separated square pixel sizes")
    ap.add_argument("--pixel", action="store_true", help="nearest-neighbour, integer factors only")
    ap.add_argument("--flatten", help="background hex to flatten onto (removes alpha)")
    ap.add_argument("--allow-upscale", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)

    jobs = []
    if a.points:
        for s in (int(x) for x in a.scales.split(",")):
            suffix = "" if s == 1 else f"@{s}x"
            jobs.append((a.points * s, f"{a.name}{suffix}.png"))
    if a.px:
        for p in (int(x) for x in a.px.split(",")):
            jobs.append((p, f"{a.name}-{p}.png"))
    if not jobs:
        ap.error("give --points (with --scales) or --px")

    is_svg = a.master.lower().endswith(".svg")
    base = None if is_svg else load_image(a.master)
    for px, fname in jobs:
        if is_svg:
            img = load_image(a.master, px)
        else:
            if px > base.size[0] and not a.allow_upscale:
                raise SystemExit(f"refusing to upscale {base.size[0]}px master to {px}px; "
                                 "regenerate larger or pass --allow-upscale")
            if a.pixel:
                if px % base.size[0] and base.size[0] % px:
                    raise SystemExit(f"{px}px is not an integer multiple of the {base.size[0]}px pixel-art master")
                img = base.resize((px, px), Image.NEAREST)
            else:
                img = base.resize((px, int(px * base.size[1] / base.size[0])), Image.LANCZOS)
        if a.flatten:
            bg = Image.new("RGBA", img.size, hex_to_rgb(a.flatten) + (255,))
            img = Image.alpha_composite(bg, img).convert("RGB")
        path = os.path.join(a.out_dir, fname)
        img.save(path)
        print(path)


if __name__ == "__main__":
    main()
