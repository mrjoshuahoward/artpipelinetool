"""Shared helpers for the art-director production scripts (Pillow only)."""
import os
import shutil
import subprocess
import sys
import tempfile

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    sys.exit("These scripts need Pillow: python3 -m pip install pillow")


def hex_to_rgb(h):
    h = h.strip().lstrip("#").removeprefix("0x")
    if len(h) != 6:
        raise ValueError(f"not a 6-digit hex colour: {h!r}")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def parse_palette(arg):
    """'#22B8B0,#F2C14E' or a file with one hex per line (comments with #! or //)."""
    if os.path.isfile(arg):
        vals = []
        for line in open(arg):
            line = line.split("//")[0].strip()
            if line:
                vals.append(line.split()[0])
        return [hex_to_rgb(v) for v in vals]
    return [hex_to_rgb(v) for v in arg.split(",") if v.strip()]


# --- colour science (sRGB -> CIELAB, CIE76 delta E is enough for clamp/checks)
def _lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rgb_to_lab(rgb):
    r, g, b = (_lin(v) for v in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e(a, b):
    return sum((p - q) ** 2 for p, q in zip(a, b)) ** 0.5


def luminance(rgb):
    r, g, b = (_lin(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# --- SVG rasterisation with whatever backend exists
def _inkscape():
    for p in ("inkscape", "/Applications/Inkscape.app/Contents/MacOS/inkscape"):
        if shutil.which(p) or os.path.exists(p):
            return p
    return None


def rasterize_svg(svg_path, png_path, width, height=None):
    """Render an SVG to PNG. Tries rsvg-convert, Inkscape, cairosvg, then Playwright Chromium."""
    height = height or width
    if shutil.which("rsvg-convert"):
        subprocess.run(["rsvg-convert", "-w", str(width), "-h", str(height), "-o", png_path, svg_path], check=True)
        return "rsvg-convert"
    ink = _inkscape()
    if ink:
        subprocess.run([ink, svg_path, "--export-type=png", f"--export-filename={png_path}",
                        f"--export-width={width}", f"--export-height={height}"],
                       check=True, capture_output=True)
        return "inkscape"
    try:
        import cairosvg  # type: ignore
        cairosvg.svg2png(url=svg_path, write_to=png_path, output_width=width, output_height=height)
        return "cairosvg"
    except ImportError:
        pass
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": width, "height": height})
            svg = open(svg_path).read()
            pg.set_content(f"<html><body style='margin:0;background:transparent'>"
                           f"<div style='width:{width}px;height:{height}px'>{svg}</div></body></html>")
            pg.eval_on_selector("svg", f"e=>{{e.setAttribute('width',{width});e.setAttribute('height',{height})}}")
            pg.locator("svg").screenshot(path=png_path, omit_background=True)
            b.close()
        return "playwright"
    except Exception as exc:  # noqa: BLE001
        sys.exit("No SVG rasteriser found (tried rsvg-convert, Inkscape, cairosvg, Playwright). "
                 f"Install one, e.g. `brew install librsvg`. Last error: {exc}")


def load_image(path, size=None):
    """Open a PNG/JPG/WebP, or rasterise an SVG at `size` (default 1024)."""
    if path.lower().endswith(".svg"):
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
        rasterize_svg(path, tmp, size or 1024)
        img = Image.open(tmp).convert("RGBA")
        img.load()
        os.unlink(tmp)
        return img
    img = Image.open(path).convert("RGBA")
    img.load()
    return img
