"""Text → outlines for recipes (2.1 B2).

`<ap:text>` is drawn from a committed font file into plain `<path>` outlines, so a built asset never
depends on the fonts of the machine that renders it (resvg, a browser, Xcode) and the build stays
deterministic. Shaping is deliberately simple: cmap lookup, advances, and pair kerning (GPOS
`kern` pair adjustments, else the legacy `kern` table). That covers Latin, Greek and Cyrillic UI
text: titles, captions, button labels. Scripts that need contextual shaping (Arabic, Indic) or
ligatures are not shaped; draw those in an app and register the result instead."""
from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FONT_EXTS = {".ttf", ".otf", ".ttc", ".woff"}


class TextError(Exception):
    pass


def _num(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


@dataclass
class Font:
    path: Path
    index: int
    axes: tuple[tuple[str, float], ...]
    tt: Any
    glyphs: Any          # glyph set (at the axes location for variable fonts)
    cmap: dict[int, str]
    upm: int
    ascender: float
    descender: float
    cap_height: float
    pairs: dict[tuple[str, str], int]

    def advance(self, g: str) -> float:
        return float(self.glyphs[g].width)


_CACHE: dict[tuple[str, str, int, tuple], Font] = {}


def load_font(path: Path, index: int = 0, axes: dict[str, float] | None = None) -> Font:
    try:
        from fontTools.ttLib import TTFont
    except ImportError:  # pragma: no cover - fonttools is a declared dependency
        raise TextError("text needs the fonttools package (pip install fonttools)") from None
    if path.suffix.lower() not in FONT_EXTS:
        raise TextError(f"{path.name}: fonts must be {sorted(FONT_EXTS)}")
    data = path.read_bytes()
    key_axes = tuple(sorted((axes or {}).items()))
    key = (str(path), hashlib.sha256(data).hexdigest(), index, key_axes)
    if key in _CACHE:
        return _CACHE[key]
    try:
        tt = TTFont(str(path), fontNumber=index, lazy=False)
    except Exception as e:
        raise TextError(f"{path.name}: not a readable font ({e})") from None
    if axes:
        if "fvar" not in tt:
            raise TextError(f"{path.name} is not a variable font; it has no axes to set")
        known = {a.axisTag: (a.minValue, a.maxValue) for a in tt["fvar"].axes}
        for tag, v in axes.items():
            if tag not in known:
                raise TextError(f"{path.name} has no '{tag}' axis. Axes: {sorted(known)}")
            lo, hi = known[tag]
            if not lo <= v <= hi:
                raise TextError(f"{path.name}: {tag}={v} is outside {lo}–{hi}")
        glyphs = tt.getGlyphSet(location=dict(axes))
    else:
        glyphs = tt.getGlyphSet()
    cmap = tt.getBestCmap() or {}
    upm = tt["head"].unitsPerEm
    os2 = tt["OS/2"] if "OS/2" in tt else None
    hhea = tt["hhea"]
    asc = float(getattr(os2, "sTypoAscender", 0) or hhea.ascent)
    desc = float(getattr(os2, "sTypoDescender", 0) or hhea.descent)
    cap = float(getattr(os2, "sCapHeight", 0) or 0) or asc * 0.7
    font = Font(path=path, index=index, axes=key_axes, tt=tt, glyphs=glyphs, cmap=cmap, upm=upm,
                ascender=asc, descender=desc, cap_height=cap, pairs=_kerning(tt))
    _CACHE[key] = font
    return font


def _kerning(tt: Any) -> dict[tuple[str, str], int]:
    """Pair kerning: GPOS `kern` pair lookups (formats 1 and 2), else the legacy kern table."""
    pairs: dict[tuple[str, str], int] = {}
    if "GPOS" in tt and tt["GPOS"].table.FeatureList and tt["GPOS"].table.LookupList:
        gpos = tt["GPOS"].table
        idx: list[int] = []
        for fr in gpos.FeatureList.FeatureRecord:
            if fr.FeatureTag == "kern":
                idx += [i for i in fr.Feature.LookupListIndex if i not in idx]
        glyph_order = tt.getGlyphOrder()
        for i in idx:
            lookup = gpos.LookupList.Lookup[i]
            for st in lookup.SubTable:
                if lookup.LookupType == 9:
                    if st.ExtensionLookupType != 2:
                        continue
                    st = st.ExtSubTable
                elif lookup.LookupType != 2:
                    continue
                _pair_subtable(st, pairs, glyph_order)
        if pairs:
            return pairs
    if "kern" in tt:
        for sub in getattr(tt["kern"], "kernTables", []):
            for k, v in getattr(sub, "kernTable", {}).items():
                pairs.setdefault(k, v)
    return pairs


def _xadv(vr: Any) -> int:
    return int(getattr(vr, "XAdvance", 0) or 0) if vr is not None else 0


def _pair_subtable(st: Any, pairs: dict[tuple[str, str], int], glyph_order: list[str]) -> None:
    firsts = st.Coverage.glyphs
    if st.Format == 1:
        for first, ps in zip(firsts, st.PairSet):
            for rec in ps.PairValueRecord:
                v = _xadv(rec.Value1)
                if v:
                    pairs.setdefault((first, rec.SecondGlyph), v)
    elif st.Format == 2:
        c1 = st.ClassDef1.classDefs if st.ClassDef1 else {}
        c2 = st.ClassDef2.classDefs if st.ClassDef2 else {}
        by_class2: dict[int, list[str]] = {}
        for g in glyph_order:
            by_class2.setdefault(c2.get(g, 0), []).append(g)
        for first in firsts:
            row = st.Class1Record[c1.get(first, 0)].Class2Record
            for k, rec in enumerate(row):
                v = _xadv(rec.Value1)
                if v:
                    for second in by_class2.get(k, []):
                        pairs.setdefault((first, second), v)


@dataclass
class Layout:
    d: str               # SVG path data for every glyph
    lines: list[str]
    font_size: float
    width: float         # widest line, px
    top: float           # cap-height top of the first line
    bottom: float        # baseline of the last line


def _glyph_run(font: Font, line: str) -> list[str]:
    out, missing = [], []
    for ch in line:
        g = font.cmap.get(ord(ch))
        if g is None:
            missing.append(ch)
        else:
            out.append(g)
    if missing:
        shown = "".join(dict.fromkeys(missing))
        raise TextError(f"{font.path.name} has no glyph for {shown!r}; use a font that covers it")
    return out


def _measure(font: Font, glyphs: list[str], scale: float, spacing: float) -> list[float]:
    """Pen x before each glyph, plus the final width as the last element."""
    xs, x = [], 0.0
    for i, g in enumerate(glyphs):
        xs.append(x)
        x += font.advance(g) * scale
        if i + 1 < len(glyphs):
            x += font.pairs.get((g, glyphs[i + 1]), 0) * scale + spacing
    xs.append(x)
    return xs


def _width(font: Font, line: str, scale: float, spacing: float) -> float:
    return _measure(font, _glyph_run(font, line), scale, spacing)[-1]


def _wrap(font: Font, para: str, scale: float, spacing: float, max_width: float) -> list[str]:
    words = para.split(" ")
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}" if cur else w
        if cur and _width(font, trial, scale, spacing) > max_width:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    lines.append(cur)
    return lines


def layout(
    font: Font,
    paragraphs: list[str],
    *,
    size: float,
    x: float = 0.0,
    y: float = 0.0,
    anchor: str = "start",
    valign: str = "baseline",
    max_width: float | None = None,
    fit: str = "wrap",
    line_height: float = 1.2,
    letter_spacing: float = 0.0,
) -> Layout:
    """Lay out text and draw it as one path. `paragraphs` are explicit lines; with max_width,
    fit='wrap' breaks them at spaces and fit='shrink' scales the font down until the widest fits."""
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen

    if anchor not in ("start", "middle", "end"):
        raise TextError(f"text-anchor must be start, middle or end, not '{anchor}'")
    if valign not in ("baseline", "top", "middle", "bottom"):
        raise TextError(f"valign must be baseline, top, middle or bottom, not '{valign}'")
    if fit not in ("wrap", "shrink"):
        raise TextError(f"fit must be wrap or shrink, not '{fit}'")
    if size <= 0:
        raise TextError("font-size must be positive")
    paragraphs = [unicodedata.normalize("NFC", " ".join(p.split())) for p in paragraphs]
    scale = size / font.upm
    if max_width is not None and fit == "shrink":
        for _ in range(4):
            widest = max((_width(font, p, scale, letter_spacing) for p in paragraphs), default=0.0)
            if widest <= max_width + 1e-6:
                break
            size = size * max_width / widest
            scale = size / font.upm
        size = int(size * 100) / 100
        scale = size / font.upm
    if max_width is not None and fit == "wrap":
        lines = [ln for p in paragraphs for ln in _wrap(font, p, scale, letter_spacing, max_width)]
    else:
        lines = list(paragraphs)

    step = size * line_height
    cap = font.cap_height * scale
    block = cap + step * (len(lines) - 1)        # cap top of line 1 → baseline of the last line
    first = {"baseline": y, "top": y + cap, "middle": y - block / 2 + cap, "bottom": y - block + cap}[valign]

    pen = SVGPathPen(font.glyphs, ntos=_num)
    widest = 0.0
    for n, line in enumerate(lines):
        glyphs = _glyph_run(font, line)
        xs = _measure(font, glyphs, scale, letter_spacing)
        w = xs[-1]
        widest = max(widest, w)
        x0 = {"start": x, "middle": x - w / 2, "end": x - w}[anchor]
        base = first + n * step
        for g, gx in zip(glyphs, xs):
            tp = TransformPen(pen, (scale, 0, 0, -scale, x0 + gx, base))
            font.glyphs[g].draw(tp)
    return Layout(d=pen.getCommands(), lines=lines, font_size=size, width=widest,
                  top=first - cap, bottom=first + step * (len(lines) - 1))
