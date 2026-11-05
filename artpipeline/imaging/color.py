"""Colour maths: sRGB → CIELAB, CIE76 ΔE, WCAG luminance/contrast.
Ported from the skill's scripts/_common.py so verdicts stay comparable."""
from __future__ import annotations

from functools import lru_cache

RGB = tuple[int, int, int]
LAB = tuple[float, float, float]


def hex_to_rgb(h: str) -> RGB:
    h = h.strip().lstrip("#").removeprefix("0x")
    if len(h) != 6:
        raise ValueError(f"not a 6-digit hex colour: {h!r}")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#%02X%02X%02X" % tuple(int(v) for v in rgb)


def _lin(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


@lru_cache(maxsize=65536)
def rgb_to_lab(rgb: RGB) -> LAB:
    r, g, b = (_lin(v) for v in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e(a: LAB, b: LAB) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def luminance(rgb: tuple[float, float, float]) -> float:
    r, g, b = (_lin(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def nearest(rgb: RGB, palette: list[RGB], palette_lab: list[LAB]) -> tuple[RGB, float]:
    lab = rgb_to_lab(rgb)
    best, best_de = palette[0], float("inf")
    for p, pl in zip(palette, palette_lab):
        d = delta_e(lab, pl)
        if d < best_de:
            best, best_de = p, d
    return best, best_de
