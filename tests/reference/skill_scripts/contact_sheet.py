#!/usr/bin/env python3
"""Contact sheet: every asset at several display sizes, on the game's real backgrounds,
plus a greyscale row (silhouette / tinted-icon proxy). Use it at every review gate.

  python3 contact_sheet.py out.png a.svg b.png c.png \
      --sizes 256,64,24 --bg "#23282B,#49606B,#F2F2F2" [--labels "Jar,Bottle,Can"] [--icon-mask]

--icon-mask rounds each tile like an iOS icon (for app-icon reviews).
Assets are drawn at their true pixel size per column, so judge readability as the player will.
"""
import argparse
import os

from PIL import Image, ImageDraw, ImageFont, ImageOps

from _common import hex_to_rgb, load_image

PAD = 16


def font(size):
    for f in ("/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def rounded(img, radius_ratio=0.225):
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.size[0] - 1, img.size[1] - 1],
                                           radius=int(img.size[0] * radius_ratio), fill=255)
    out = img.copy()
    out.putalpha(Image.composite(img.getchannel("A"), mask, mask))
    return out


def grey(img):
    g = ImageOps.grayscale(img.convert("RGB")).convert("RGBA")
    g.putalpha(img.getchannel("A"))
    return g


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("assets", nargs="+")
    ap.add_argument("--sizes", default="256,64,24")
    ap.add_argument("--bg", default="#1C1C1E,#F2F2F7", help="comma-separated background hexes")
    ap.add_argument("--labels", default="")
    ap.add_argument("--icon-mask", action="store_true")
    a = ap.parse_args()

    sizes = [int(s) for s in a.sizes.split(",")]
    bgs = [hex_to_rgb(h) for h in a.bg.split(",")]
    labels = a.labels.split(",") if a.labels else [os.path.splitext(os.path.basename(p))[0] for p in a.assets]
    masters = [load_image(p, max(1024, max(sizes))) for p in a.assets]

    cell = max(sizes) + PAD
    variants = [("colour", lambda i: i), ("greyscale", grey)]
    label_w, header_h = 150, 40
    cols = len(bgs) * len(sizes)
    rows = len(masters) * len(variants)
    W = label_w + cols * cell + PAD
    H = header_h + rows * cell + PAD
    sheet = Image.new("RGB", (W, H), (236, 236, 240))
    d = ImageDraw.Draw(sheet)
    f, fs = font(14), font(11)

    for bi, bg in enumerate(bgs):
        for si, s in enumerate(sizes):
            x = label_w + (bi * len(sizes) + si) * cell
            d.text((x, 12), f"{s}px on #{'%02X%02X%02X' % bg}", fill=(40, 40, 40), font=fs)

    for mi, (m, lab) in enumerate(zip(masters, labels)):
        for vi, (vname, fn) in enumerate(variants):
            y = header_h + (mi * len(variants) + vi) * cell
            d.text((PAD, y + 8), lab, fill=(20, 20, 20), font=f)
            d.text((PAD, y + 28), vname, fill=(90, 90, 90), font=fs)
            for bi, bg in enumerate(bgs):
                for si, s in enumerate(sizes):
                    x = label_w + (bi * len(sizes) + si) * cell
                    sheet.paste(bg, (x, y, x + cell - PAD, y + cell - PAD))
                    t = fn(m).resize((s, s), Image.LANCZOS)
                    if a.icon_mask:
                        t = rounded(t)
                    off = (cell - PAD - s) // 2
                    sheet.paste(t, (x + off, y + off), t)
    sheet.save(a.out)
    print(f"wrote {a.out} ({len(masters)} assets x {len(sizes)} sizes x {len(bgs)} backgrounds)")


if __name__ == "__main__":
    main()
