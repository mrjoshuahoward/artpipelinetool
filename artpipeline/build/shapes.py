"""Geometry for the recipe shape library: `<ap:star>`, `<ap:polygon>`, `<ap:ring>`, `<ap:arc>`,
`<ap:gear>`, `<ap:burst>`. Each expands to a plain SVG `<polygon>` or `<path>`; every attribute that
isn't geometry (fill, stroke, transform, id, class, style, ...) is passed through unchanged.

Angles are degrees, 0 at 12 o'clock, increasing clockwise. Output coordinates are rounded to 3
decimals so a build is byte-for-byte reproducible."""
from __future__ import annotations

import math
from typing import Callable


class ShapeError(ValueError):
    pass


def fmt(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def pt(cx: float, cy: float, r: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return cx + r * math.sin(a), cy - r * math.cos(a)


def _pts(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{fmt(x)},{fmt(y)}" for x, y in points)


def _poly_d(points: list[tuple[float, float]]) -> str:
    head, *rest = points
    return f"M{fmt(head[0])},{fmt(head[1])}" + "".join(f"L{fmt(x)},{fmt(y)}" for x, y in rest) + "Z"


def _circle_d(cx: float, cy: float, r: float) -> str:
    return (f"M{fmt(cx)},{fmt(cy - r)}A{fmt(r)},{fmt(r)} 0 1 1 {fmt(cx)},{fmt(cy + r)}"
            f"A{fmt(r)},{fmt(r)} 0 1 1 {fmt(cx)},{fmt(cy - r)}Z")


class Args:
    """Typed access to an element's geometry attributes; anything read is consumed."""

    def __init__(self, tag: str, attrs: dict[str, str]):
        self.tag = tag
        self.attrs = dict(attrs)
        self.used: set[str] = set()

    def num(self, name: str, default: float | None = None, *, min_: float | None = None,
            max_: float | None = None) -> float:
        self.used.add(name)
        raw = self.attrs.get(name)
        if raw is None:
            if default is None:
                raise ShapeError(f"<ap:{self.tag}> needs a '{name}' attribute")
            return default
        try:
            v = float(raw)
        except ValueError:
            raise ShapeError(f"<ap:{self.tag}> {name}='{raw}' is not a number") from None
        if (min_ is not None and v < min_) or (max_ is not None and v > max_):
            rng = f"{min_ if min_ is not None else '-inf'}..{max_ if max_ is not None else 'inf'}"
            raise ShapeError(f"<ap:{self.tag}> {name}={raw} is out of range ({rng})")
        return v

    def int_(self, name: str, default: int | None = None, *, min_: int = 1) -> int:
        v = self.num(name, None if default is None else float(default), min_=min_)
        if v != int(v):
            raise ShapeError(f"<ap:{self.tag}> {name} must be a whole number")
        return int(v)

    def flag(self, name: str) -> bool:
        self.used.add(name)
        return self.attrs.get(name, "false").strip().lower() in ("1", "true", "yes")

    def rest(self) -> dict[str, str]:
        return {k: v for k, v in self.attrs.items() if k not in self.used}


def star(a: Args) -> tuple[str, dict[str, str]]:
    cx, cy, r = a.num("cx"), a.num("cy"), a.num("r", min_=0)
    n = a.int_("points", 5, min_=2)
    inner = a.num("inner", 0.5, min_=0, max_=1)
    rot = a.num("rotate", 0)
    pts = [pt(cx, cy, r if i % 2 == 0 else r * inner, rot + i * 180 / n) for i in range(2 * n)]
    return "polygon", {"points": _pts(pts)}


def polygon(a: Args) -> tuple[str, dict[str, str]]:
    cx, cy, r = a.num("cx"), a.num("cy"), a.num("r", min_=0)
    n = a.int_("sides", min_=3)
    rot = a.num("rotate", 0)
    return "polygon", {"points": _pts([pt(cx, cy, r, rot + i * 360 / n) for i in range(n)])}


def ring(a: Args) -> tuple[str, dict[str, str]]:
    cx, cy, r = a.num("cx"), a.num("cy"), a.num("r", min_=0)
    w = a.num("width", min_=0)
    if w >= r:
        raise ShapeError("<ap:ring> width must be smaller than r (use a circle for a disc)")
    return "path", {"d": _circle_d(cx, cy, r) + _circle_d(cx, cy, r - w), "fill-rule": "evenodd"}


def arc(a: Args) -> tuple[str, dict[str, str]]:
    cx, cy, r = a.num("cx"), a.num("cy"), a.num("r", min_=0)
    start, end = a.num("start"), a.num("end")
    sector = a.flag("sector")
    sweep = end - start
    if sweep <= 0:
        raise ShapeError("<ap:arc> end must be greater than start (degrees clockwise from 12 o'clock)")
    if sweep >= 360:
        d = _circle_d(cx, cy, r)
        return "path", {"d": d}
    x0, y0 = pt(cx, cy, r, start)
    x1, y1 = pt(cx, cy, r, end)
    large = 1 if sweep > 180 else 0
    body = f"A{fmt(r)},{fmt(r)} 0 {large} 1 {fmt(x1)},{fmt(y1)}"
    if sector:
        d = f"M{fmt(cx)},{fmt(cy)}L{fmt(x0)},{fmt(y0)}{body}Z"
    else:
        d = f"M{fmt(x0)},{fmt(y0)}{body}"
    return "path", {"d": d}


def gear(a: Args) -> tuple[str, dict[str, str]]:
    cx, cy, r = a.num("cx"), a.num("cy"), a.num("r", min_=0)
    n = a.int_("teeth", min_=3)
    depth = a.num("depth", 0.18, min_=0, max_=0.9)
    hole = a.num("hole", 0, min_=0, max_=0.95)
    rot = a.num("rotate", 0)
    p, ri = 360 / n, r * (1 - depth)
    pts: list[tuple[float, float]] = []
    for i in range(n):
        base = rot + i * p
        pts += [pt(cx, cy, ri, base - 0.3 * p), pt(cx, cy, r, base - 0.18 * p),
                pt(cx, cy, r, base + 0.18 * p), pt(cx, cy, ri, base + 0.3 * p)]
    d = _poly_d(pts)
    attrs = {"d": d}
    if hole > 0:
        attrs["d"] = d + _circle_d(cx, cy, r * hole)
        attrs["fill-rule"] = "evenodd"
    return "path", attrs


def burst(a: Args) -> tuple[str, dict[str, str]]:
    cx, cy, r = a.num("cx"), a.num("cy"), a.num("r", min_=0)
    n = a.int_("rays", min_=2)
    inner = a.num("inner", 0, min_=0, max_=0.99)
    width = a.num("width", 0.5, min_=0.01, max_=1)
    rot = a.num("rotate", 0)
    p = 360 / n
    hw = width * p / 2
    parts = []
    for i in range(n):
        c = rot + i * p
        if inner == 0:
            ray = [(cx, cy), pt(cx, cy, r, c - hw), pt(cx, cy, r, c + hw)]
        else:
            ri = r * inner
            ray = [pt(cx, cy, ri, c - hw), pt(cx, cy, r, c - hw), pt(cx, cy, r, c + hw), pt(cx, cy, ri, c + hw)]
        parts.append(_poly_d(ray))
    return "path", {"d": "".join(parts)}


SHAPES: dict[str, Callable[[Args], tuple[str, dict[str, str]]]] = {
    "star": star, "polygon": polygon, "ring": ring, "arc": arc, "gear": gear, "burst": burst,
}


def expand(tag: str, attrs: dict[str, str]) -> tuple[str, dict[str, str]]:
    """Return (svg_tag, attributes) for one shape element."""
    a = Args(tag, attrs)
    svg_tag, geo = SHAPES[tag](a)
    out = a.rest()
    out.update(geo)
    return svg_tag, out
