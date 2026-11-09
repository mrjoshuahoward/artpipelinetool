"""The `compose` recipe compiler (2.1 B2): a stack of layers → one plain SVG.

Layers are drawn bottom to top on a canvas the size of the asset's master:

* `svg` — an SVG recipe file, compiled like an `svg` recipe source (tokens, params, includes,
  shapes, `<ap:text>`), placed into its box.
* `image` — a local raster or SVG file, embedded (screenshots, painted backgrounds, device frames).
* `asset` — another asset's approved output (key art from approved sprites, an icon on a banner).
  The approved file's hash is part of the fingerprint, so re-approving it makes this asset stale.
* `text` — drawn as outlines from a committed font (see text.py).
* `fill` — a solid, optionally rounded rectangle.

Every layer can take `opacity`, `rotate` and a drop `shadow`; image and asset layers can round
their corners with `radius`. The result is an ordinary SVG, so raster classes are rendered by the
same resvg pass as everything else and vector classes keep the vectors."""
from __future__ import annotations

import base64
import hashlib
import html
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable

from artpipeline.build.svg import (
    AP_NS, SVG_NS, BuildError, Compiled, _as_written, _children_of, _Ctx, _expand_shapes, _is_ap, _load,
    _local, _MIME, _new_svg, _substitute, embed_image, resolve_font, resolve_params,
)

BUILDER_VERSION = "compose-1"
_FIT = {"contain": "xMidYMid meet", "cover": "xMidYMid slice", "stretch": "none"}

AssetResolver = Callable[[str], Path]


def _n(v: float) -> str:
    s = f"{round(float(v), 3):.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _color(v: str, ctx: _Ctx, where: str) -> str:
    if v.startswith("$"):
        name = v[1:]
        if name not in ctx.tokens:
            raise BuildError(f"{where}: colour '{v}' names an undefined token. Tokens: {sorted(ctx.tokens)}")
        ctx.tokens_used[name] = ctx.tokens[name]
        return ctx.tokens[name]
    if "{{" in v:
        return html.unescape(_substitute(v, ctx, where))
    return v


def _svg(tag: str, attrs: dict[str, str] | None = None) -> ET.Element:
    return ET.Element(f"{{{SVG_NS}}}{tag}", attrs or {})


def _viewbox(nodes: list[ET.Element], master: tuple[int, int]) -> str:
    if len(nodes) == 1 and _local(nodes[0].tag) == (SVG_NS, "svg"):
        root = nodes[0]
        if root.get("viewBox"):
            return root.get("viewBox")
        w, h = root.get("width"), root.get("height")
        try:
            return f"0 0 {_n(float(str(w).removesuffix('px')))} {_n(float(str(h).removesuffix('px')))}"
        except (TypeError, ValueError):
            pass
    return f"0 0 {master[0]} {master[1]}"


def compile_compose(
    root: Path,
    *,
    layers: list[dict[str, Any]],
    background: str | None,
    params: dict[str, Any],
    tokens: dict[str, str],
    asset: dict[str, Any],
    master: tuple[int, int],
    assets: AssetResolver | None = None,
) -> Compiled:
    root = root.resolve()
    refs: dict[str, str] = {}
    ctx = _Ctx(root=root, tokens=dict(tokens), params=resolve_params(params, tokens, refs), asset=asset,
               param_tokens=refs)
    if not layers:
        raise BuildError("a compose recipe needs at least one layer")
    W, H = master
    doc = _new_svg(master)
    defs = _svg("defs")
    doc.append(defs)
    if background:
        doc.append(_svg("rect", {"width": str(W), "height": str(H), "fill": _color(background, ctx, "background")}))

    for i, ly in enumerate(layers, start=1):
        where = f"layer {i}"
        x, y = ly.get("at") or (0, 0)
        w, h = ly.get("size") or (W, H)
        box = {"x": _n(x), "y": _n(y), "width": _n(w), "height": _n(h)}
        fit = _FIT[ly.get("fit") or "contain"]
        kind = next(k for k in ("svg", "image", "asset", "text", "fill") if ly.get(k) is not None)

        if kind == "svg":
            saved = (ctx.params, ctx.param_tokens)
            lrefs = dict(refs)
            ctx.params = {**ctx.params, **resolve_params(ly.get("params") or {}, tokens, lrefs)}
            ctx.param_tokens = lrefs
            try:
                nodes = _load(root / ly["svg"], ctx)
            finally:
                ctx.params, ctx.param_tokens = saved
            if any(_is_ap(n) and _local(n.tag)[1] in ("slot", "part") for n in nodes):
                raise BuildError(f"{where}: <ap:slot>/<ap:part> belong to svg templates, not compose layers")
            el = _svg("svg", {**box, "viewBox": _viewbox(nodes, master), "preserveAspectRatio": fit})
            el.extend(_children_of(nodes))
        elif kind == "image":
            el = _svg("image", {**box, "preserveAspectRatio": fit, "href": ly["image"]})
            embed_image(el, root, ctx, where)
        elif kind == "asset":
            aid = ly["asset"]
            if aid == asset.get("id"):
                raise BuildError(f"{where}: an asset can't be a layer of itself")
            if assets is None:
                raise BuildError(f"{where}: asset layers need the pipeline (no resolver)")
            p = assets(aid)  # raises BuildError when it isn't approved yet
            data = p.read_bytes()
            mime = _MIME.get(p.suffix.lower())
            if mime is None:
                raise BuildError(f"{where}: approved file of '{aid}' has unsupported type {p.suffix}")
            ctx.inputs[f"asset:{aid}"] = hashlib.sha256(data).hexdigest()
            el = _svg("image", {**box, "preserveAspectRatio": fit,
                                "href": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"})
        elif kind == "fill":
            el = _svg("rect", {**box, "fill": _color(ly["fill"], ctx, where)})
            if ly.get("radius"):
                el.set("rx", _n(ly["radius"]))
        else:  # text
            attrs = {"font": ly["font"], "font-size": _n(ly["font_size"]), "x": _n(x), "y": _n(y),
                     "text-anchor": ly.get("anchor") or "start", "valign": ly.get("valign") or "baseline",
                     "line-height": _n(ly.get("line_height", 1.2)),
                     "letter-spacing": _n(ly.get("letter_spacing") or 0),
                     "fill": _color(ly.get("color") or "#000000", ctx, where)}
            if ly.get("max_width"):
                attrs["max-width"] = _n(ly["max_width"])
                attrs["fit"] = "shrink" if ly.get("shrink") else "wrap"
            if ly.get("axes"):
                attrs["axes"] = " ".join(f"{k}={_n(v)}" for k, v in sorted(ly["axes"].items()))
            if ly.get("stroke") and ly.get("stroke_width"):
                attrs.update({"stroke": _color(ly["stroke"], ctx, where), "stroke-width": _n(ly["stroke_width"]),
                              "stroke-linejoin": "round", "paint-order": "stroke"})
            el = ET.Element(f"{{{AP_NS}}}text", attrs)
            lines = html.unescape(_substitute(ly["text"], ctx, where)).split("\n")
            el.text = lines[0]
            for ln in lines[1:]:
                br = ET.SubElement(el, f"{{{AP_NS}}}br")
                br.tail = ln
            resolve_font(el, root, ctx, where)

        r = ly.get("radius") or 0
        if r and kind in ("image", "asset", "svg"):
            clip = _svg("clipPath", {"id": f"ap-clip-{i}"})
            clip.append(_svg("rect", {**box, "rx": _n(r)}))
            defs.append(clip)
            wrap = _svg("g", {"clip-path": f"url(#ap-clip-{i})"})
            wrap.append(el)
            el = wrap

        g_attrs: dict[str, str] = {}
        if (ly.get("opacity", 1)) != 1:
            g_attrs["opacity"] = _n(ly["opacity"])
        if ly.get("rotate"):
            if kind == "text":
                cx, cy = x, y
            else:
                cx, cy = x + w / 2, y + h / 2
            g_attrs["transform"] = f"rotate({_n(ly['rotate'])} {_n(cx)} {_n(cy)})"
        sh = ly.get("shadow")
        if sh:
            f = _svg("filter", {"id": f"ap-shadow-{i}", "x": "-50%", "y": "-50%", "width": "200%", "height": "200%",
                                "color-interpolation-filters": "sRGB"})
            f.append(_svg("feDropShadow", {
                "dx": _n(sh.get("dx", 0)), "dy": _n(sh.get("dy", 8)), "stdDeviation": _n(sh.get("blur", 12) / 2),
                "flood-color": _color(sh.get("color") or "#000000", ctx, where),
                "flood-opacity": _n(sh.get("opacity", 0.35))}))
            defs.append(f)
            g_attrs["filter"] = f"url(#ap-shadow-{i})"
        if g_attrs:
            g = _svg("g", g_attrs)
            g.append(el)
            el = g
        doc.append(el)

    if not len(defs):
        doc.remove(defs)
    _expand_shapes(doc)
    for el in doc.iter():
        if _is_ap(el):
            raise BuildError(f"<ap:{_local(el.tag)[1]}> left over after the build")
    data = ET.tostring(doc, encoding="utf-8", xml_declaration=True)
    fp = hashlib.sha256(BUILDER_VERSION.encode() + b"\n" + data).hexdigest()
    return Compiled(svg=data, fingerprint=fp, inputs=dict(sorted(ctx.inputs.items())),
                    tokens=dict(sorted(ctx.tokens_used.items())),
                    params={k: _as_written(v) for k, v in sorted(params.items())},
                    kind="compose", builder=BUILDER_VERSION,
                    layers=hashlib.sha256(json.dumps([layers, background], sort_keys=True).encode()).hexdigest())
