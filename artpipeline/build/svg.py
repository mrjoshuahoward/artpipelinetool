"""The `svg` recipe compiler: template + per-asset source + named colours → one plain SVG.

A recipe is ordinary SVG plus a few additions:

* `{{ name }}` substitutes a value: `tokens.<name>` (a named colour from the style lock or brief),
  `params.<name>` (the asset's build params), `asset.id|subject|group|destination`. A bare name is
  looked up in params, then tokens. A param whose value starts with `$` names a token
  (`band: $gold`). Unknown names are an error, never an empty string.
* `<ap:slot name="..."/>` in a template marks where the per-asset source goes (default name
  `content`). In the source, `<ap:part name="...">` fills a named slot; everything else fills
  `content`. An unfilled slot keeps its own children as the default.
* `<ap:include src="parts/rivet.svg"/>` inlines another file (relative to the including file).
* `<image href="local.png">` is embedded as a data URI, so the built file stands alone.
* Shapes: `<ap:star>`, `<ap:polygon>`, `<ap:ring>`, `<ap:arc>`, `<ap:gear>`, `<ap:burst>` (see shapes.py).
* `<ap:text font="fonts/Title.ttf" font-size="96" x=".." y="..">Level 3</ap:text>` is drawn from the
  committed font into a plain `<path>` (see text.py); `<ap:br/>` breaks a line. Plain `<text>` is
  refused because it would render with whatever fonts the viewing machine has.

The `ap:` prefix needs no namespace declaration. The output is deterministic: the same inputs give
the same bytes, and its hash is the build fingerprint used for stale tracking."""
from __future__ import annotations

import base64
import hashlib
import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from artpipeline.build import shapes, text as textmod

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
AP_NS = "https://github.com/mrjoshuahoward/artpipelinetool/ns/build"
BUILDER_VERSION = "svg-1"  # bump only when the same recipe would compile to different bytes

ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)

_SUB = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")
_NAME = re.compile(r"^[A-Za-z_][\w-]*(\.[A-Za-z_][\w-]*)?$")
_PROLOG = re.compile(r"<\?xml[^>]*\?>|<!DOCTYPE[^>]*>", re.IGNORECASE)
_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
         ".gif": "image/gif", ".svg": "image/svg+xml"}
MAX_DEPTH = 8
STRUCTURAL = ("slot", "part", "include", "text", "br")
ASSET_FIELDS = ("id", "subject", "group", "destination")


class BuildError(Exception):
    pass


@dataclass
class Compiled:
    svg: bytes                      # the built file's bytes (SVG, or PNG for derive)
    fingerprint: str
    inputs: dict[str, str]          # file → sha256 (relative to the pipeline root when inside it)
    tokens: dict[str, str]          # tokens the recipe actually used
    params: dict[str, str]          # as written in the brief ($token references unresolved)
    kind: str = "svg"
    builder: str = BUILDER_VERSION
    layers: str | None = None       # compose: sha256 of the layer stack as written in the brief
    ext: str = ".svg"               # the built file's type (derive builds a .png)
    atlas: dict[str, Any] | None = None   # derive: frame rectangles, cell, animation

    def record(self) -> dict[str, Any]:
        out = {"kind": self.kind, "builder": self.builder, "fingerprint": self.fingerprint,
               "inputs": self.inputs, "tokens": self.tokens, "params": self.params}
        if self.layers:
            out["layers"] = self.layers
        if self.atlas:
            out["atlas"] = self.atlas
        return out


@dataclass
class _Ctx:
    root: Path
    tokens: dict[str, str]
    params: dict[str, str]
    asset: dict[str, Any]
    inputs: dict[str, str] = field(default_factory=dict)
    tokens_used: dict[str, str] = field(default_factory=dict)
    param_tokens: dict[str, str] = field(default_factory=dict)  # param → token it names ($gold)
    stack: list[Path] = field(default_factory=list)

    def rel(self, p: Path) -> str:
        try:
            return p.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return str(p.resolve())


def _ap(tag: str) -> str:
    return f"{{{AP_NS}}}{tag}"


def _local(tag: Any) -> tuple[str | None, str]:
    if not isinstance(tag, str):
        return None, ""
    if tag.startswith("{"):
        ns, _, name = tag[1:].partition("}")
        return ns, name
    return None, tag


def _is_ap(el: ET.Element, name: str | None = None) -> bool:
    ns, local = _local(el.tag)
    return ns == AP_NS and (name is None or local == name)


def resolve_params(raw: dict[str, Any], tokens: dict[str, str],
                   refs: dict[str, str] | None = None) -> dict[str, str]:
    out = {}
    for k, v in raw.items():
        if isinstance(v, bool):
            v = "true" if v else "false"
        v = str(v)
        if v.startswith("$"):
            name = v[1:]
            if name not in tokens:
                raise BuildError(f"param '{k}' names token '{name}', which is not defined. "
                                 f"Tokens: {sorted(tokens)}")
            v = tokens[name]
            if refs is not None:
                refs[k] = name
        out[k] = v
    return out


def _as_written(v: Any) -> str:
    """Params are recorded as written ($gold, not its colour): token values are recorded separately."""
    return ("true" if v else "false") if isinstance(v, bool) else str(v)


def _substitute(text: str, ctx: _Ctx, where: str) -> str:
    def one(m: re.Match) -> str:
        name = m.group(1)
        line = text.count("\n", 0, m.start()) + 1
        if not _NAME.match(name):
            raise BuildError(f"{where}:{line}: '{{{{ {name} }}}}' is not a name (no expressions in recipes)")
        scope, _, key = name.partition(".")
        if not key:
            scope, key = ("params", name) if name in ctx.params else ("tokens", name)
        if scope == "params" and key in ctx.params:
            val = ctx.params[key]
            if key in ctx.param_tokens:
                tok = ctx.param_tokens[key]
                ctx.tokens_used[tok] = ctx.tokens[tok]
        elif scope == "tokens" and key in ctx.tokens:
            val = ctx.tokens[key]
            ctx.tokens_used[key] = val
        elif scope == "asset" and key in ASSET_FIELDS:
            val = str(ctx.asset.get(key) or "")
        else:
            raise BuildError(
                f"{where}:{line}: unknown name '{name}'. Params: {sorted(ctx.params)}; "
                f"tokens: {sorted(ctx.tokens)}; asset: {list(ASSET_FIELDS)}")
        return html.escape(val, quote=True)

    return _SUB.sub(one, text)


def _load(path: Path, ctx: _Ctx) -> list[ET.Element]:
    """Read one recipe file: substitute, parse, inline includes and images. Returns its top-level
    elements (one <svg> for a document, several for a fragment)."""
    path = path.resolve()
    if path in ctx.stack:
        chain = " → ".join(ctx.rel(p) for p in [*ctx.stack, path])
        raise BuildError(f"include cycle: {chain}")
    if len(ctx.stack) >= MAX_DEPTH:
        raise BuildError(f"includes nested deeper than {MAX_DEPTH} at {ctx.rel(path)}")
    if not path.is_file():
        where = f" (included from {ctx.rel(ctx.stack[-1])})" if ctx.stack else ""
        raise BuildError(f"recipe file not found: {ctx.rel(path)}{where}")
    raw = path.read_bytes()
    ctx.inputs[ctx.rel(path)] = hashlib.sha256(raw).hexdigest()
    where = ctx.rel(path)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise BuildError(f"{where}: not UTF-8 text") from None
    text = _PROLOG.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    text = _substitute(text, ctx, where)
    wrapped = f'<ap:root xmlns="{SVG_NS}" xmlns:xlink="{XLINK_NS}" xmlns:ap="{AP_NS}">{text}</ap:root>'
    try:
        top = ET.fromstring(wrapped)
    except ET.ParseError as e:
        line, col = e.position
        raise BuildError(f"{where}:{line}: not valid SVG/XML ({e.msg if hasattr(e, 'msg') else e})") from None
    ctx.stack.append(path)
    try:
        _inline(top, path.parent, ctx)
    finally:
        ctx.stack.pop()
    return list(top)


def _children_of(nodes: list[ET.Element]) -> list[ET.Element]:
    """A loaded document contributes its <svg>'s children; a fragment contributes itself."""
    if len(nodes) == 1 and _local(nodes[0].tag) == (SVG_NS, "svg"):
        return list(nodes[0])
    return nodes


def _inline(parent: ET.Element, base: Path, ctx: _Ctx) -> None:
    i = 0
    while i < len(parent):
        el = parent[i]
        if _is_ap(el, "include"):
            src = el.get("src")
            if not src:
                raise BuildError(f"{ctx.rel(ctx.stack[-1])}: <ap:include> needs src=")
            nodes = _children_of(_load(base / src, ctx))
            parent.remove(el)
            for k, n in enumerate(nodes):
                parent.insert(i + k, n)
            i += len(nodes)
            continue
        where = ctx.rel(ctx.stack[-1]) if ctx.stack else "recipe"
        if _local(el.tag) == (SVG_NS, "image"):
            embed_image(el, base, ctx, where)
        elif _is_ap(el, "text"):
            resolve_font(el, base, ctx, where)
        _inline(el, base, ctx)
        i += 1


def embed_image(el: ET.Element, base: Path, ctx: _Ctx, where: str) -> None:
    for key in ("href", f"{{{XLINK_NS}}}href"):
        href = el.get(key)
        if not href or href.startswith(("data:", "#")):
            continue
        if re.match(r"^[a-z][a-z0-9+.-]*://", href, re.IGNORECASE):
            raise BuildError(f"{where}: <image href='{href}'> is remote; recipes may only "
                             "use local files so builds are reproducible offline")
        p = (base / href).resolve()
        if not p.is_file():
            raise BuildError(f"{where}: image not found: {href}")
        mime = _MIME.get(p.suffix.lower())
        if mime is None:
            raise BuildError(f"{where}: unsupported image type {p.suffix}")
        data = p.read_bytes()
        ctx.inputs[ctx.rel(p)] = hashlib.sha256(data).hexdigest()
        el.set(key, f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}")


_FONT_ATTR = f"{{{AP_NS}}}font-path"   # internal: the resolved font file, set while inlining


def resolve_font(el: ET.Element, base: Path, ctx: _Ctx, where: str) -> None:
    """Find an <ap:text>'s font relative to the file that uses it and record it as an input."""
    font = el.get("font")
    if not font:
        raise BuildError(f"{where}: <ap:text> needs font= (a committed .ttf/.otf file)")
    if re.match(r"^[a-z][a-z0-9+.-]*://", font, re.IGNORECASE):
        raise BuildError(f"{where}: font '{font}' is remote; commit the font file with the project")
    p = (base / font).resolve()
    if not p.is_file():
        raise BuildError(f"{where}: font not found: {font}")
    ctx.inputs[ctx.rel(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    el.set(_FONT_ATTR, str(p))
    el.set(f"{{{AP_NS}}}where", where)


def _new_svg(master: tuple[int, int]) -> ET.Element:
    w, h = master
    return ET.Element(f"{{{SVG_NS}}}svg", {"viewBox": f"0 0 {w} {h}", "width": str(w), "height": str(h)})


def _document(nodes: list[ET.Element], master: tuple[int, int]) -> ET.Element:
    if len(nodes) == 1 and _local(nodes[0].tag) == (SVG_NS, "svg"):
        return nodes[0]
    doc = _new_svg(master)
    doc.extend(nodes)
    return doc


def _fill_slots(doc: ET.Element, content: list[ET.Element]) -> None:
    parts: dict[str, list[ET.Element]] = {}
    rest: list[ET.Element] = []
    for n in content:
        if _is_ap(n, "part"):
            name = n.get("name")
            if not name:
                raise BuildError("<ap:part> needs name=")
            parts[name] = list(n)
        else:
            rest.append(n)
    if rest:
        parts.setdefault("content", rest)
    used: set[str] = set()

    def walk(parent: ET.Element) -> None:
        i = 0
        while i < len(parent):
            el = parent[i]
            if _is_ap(el, "slot"):
                name = el.get("name", "content")
                fill = parts.get(name)
                if fill is not None:
                    used.add(name)
                nodes = fill if fill is not None else list(el)
                parent.remove(el)
                for k, n in enumerate(nodes):
                    parent.insert(i + k, n)
                i += len(nodes)
                continue
            walk(el)
            i += 1

    walk(doc)
    extra = sorted(set(parts) - used)
    if extra:
        raise BuildError(f"the source fills slot(s) {extra} but the template has no <ap:slot name=...> for them")


_TEXT_ATTRS = {"font", "font-size", "size", "x", "y", "text-anchor", "anchor", "valign", "max-width",
               "fit", "line-height", "letter-spacing", "axes", "font-index", _FONT_ATTR, f"{{{AP_NS}}}where"}


def _float(attrs: dict[str, str], key: str, default: float | None, where: str) -> float | None:
    v = attrs.get(key)
    if v is None or v == "":
        return default
    try:
        return float(v.removesuffix("px"))
    except ValueError:
        raise BuildError(f"{where}: <ap:text {key}='{v}'> is not a number") from None


def text_lines(el: ET.Element, where: str) -> list[str]:
    lines, cur = [], el.text or ""
    for ch in el:
        if not _is_ap(ch, "br"):
            raise BuildError(f"{where}: <ap:text> may only contain text and <ap:br/>")
        lines.append(cur)
        cur = ch.tail or ""
    lines.append(cur)
    return lines


def expand_text(el: ET.Element) -> ET.Element:
    a = dict(el.attrib)
    where = a.get(f"{{{AP_NS}}}where", "recipe")
    if _FONT_ATTR not in a:
        raise BuildError(f"{where}: <ap:text> needs font= (a committed .ttf/.otf file)")
    size = _float(a, "font-size", None, where) or _float(a, "size", None, where)
    if not size:
        raise BuildError(f"{where}: <ap:text> needs font-size=")
    axes = {}
    for part in (a.get("axes") or "").replace(",", " ").split():
        tag, _, val = part.partition("=")
        try:
            axes[tag] = float(val)
        except ValueError:
            raise BuildError(f"{where}: axes='{a['axes']}' must look like 'wght=700 wdth=90'") from None
    try:
        font = textmod.load_font(Path(a[_FONT_ATTR]), int(_float(a, "font-index", 0, where)), axes)
        lay = textmod.layout(
            font, text_lines(el, where), size=size, x=_float(a, "x", 0.0, where), y=_float(a, "y", 0.0, where),
            anchor=a.get("text-anchor") or a.get("anchor") or "start", valign=a.get("valign", "baseline"),
            max_width=_float(a, "max-width", None, where), fit=a.get("fit", "wrap"),
            line_height=_float(a, "line-height", 1.2, where), letter_spacing=_float(a, "letter-spacing", 0.0, where))
    except textmod.TextError as e:
        raise BuildError(f"{where}: {e}") from None
    attrs = {k: v for k, v in a.items() if k not in _TEXT_ATTRS}
    attrs = {"d": lay.d, **attrs, "aria-label": " / ".join(lay.lines)}
    return ET.Element(f"{{{SVG_NS}}}path", attrs)


def _expand_shapes(parent: ET.Element) -> None:
    for i, el in enumerate(list(parent)):
        ns, local = _local(el.tag)
        if ns == AP_NS and local == "text":
            new = expand_text(el)
            new.tail = el.tail
            parent.remove(el)
            parent.insert(i, new)
        elif ns == SVG_NS and local == "text":
            raise BuildError("plain <text> renders with whatever fonts the viewing machine has; use "
                             "<ap:text font='fonts/X.ttf' font-size='..'> so the text is drawn as outlines")
        elif ns == AP_NS:
            if local not in shapes.SHAPES:
                where = "only in templates" if local == "slot" else "only in a source used with a template" \
                    if local == "part" else "only inside <ap:text>" if local == "br" else None
                if where:
                    raise BuildError(f"<ap:{local}> is allowed {where}")
                raise BuildError(f"unknown element <ap:{local}>. Known: "
                                 f"{sorted([*shapes.SHAPES, *STRUCTURAL])}")
            if len(el):
                raise BuildError(f"<ap:{local}> takes no child elements")
            try:
                tag, attrs = shapes.expand(local, dict(el.attrib))
            except shapes.ShapeError as e:
                raise BuildError(str(e)) from None
            new = ET.Element(f"{{{SVG_NS}}}{tag}", attrs)
            new.tail = el.tail
            parent.remove(el)
            parent.insert(i, new)
        else:
            _expand_shapes(el)


def compile_svg(
    root: Path,
    *,
    source: str | None,
    template: str | None,
    params: dict[str, Any],
    tokens: dict[str, str],
    asset: dict[str, Any],
    master: tuple[int, int],
) -> Compiled:
    """Compile one asset's svg recipe. Paths are relative to the pipeline root."""
    root = root.resolve()
    refs: dict[str, str] = {}
    ctx = _Ctx(root=root, tokens=dict(tokens), params=resolve_params(params, tokens, refs), asset=asset,
               param_tokens=refs)
    if not source and not template:
        raise BuildError("an svg recipe needs a source, a template, or both")
    src_nodes = _load(root / source, ctx) if source else []
    if template:
        doc = _document(_load(root / template, ctx), master)
        _fill_slots(doc, _children_of(src_nodes))
    else:
        doc = _document(src_nodes, master)
    _expand_shapes(doc)
    for el in doc.iter():
        if _is_ap(el):
            raise BuildError(f"<ap:{_local(el.tag)[1]}> left over after the build")
    data = ET.tostring(doc, encoding="utf-8", xml_declaration=True)
    fp = hashlib.sha256(BUILDER_VERSION.encode() + b"\n" + data).hexdigest()
    return Compiled(svg=data, fingerprint=fp, inputs=dict(sorted(ctx.inputs.items())),
                    tokens=dict(sorted(ctx.tokens_used.items())),
                    params={k: _as_written(v) for k, v in sorted(params.items())})


def describe_change(old: dict[str, Any] | None, new: dict[str, Any]) -> str:
    """One line saying what differs between two build records (for change_from_previous)."""
    if not old:
        return "first build from a recipe"
    bits = []
    if old.get("layers") and new.get("layers") and old["layers"] != new["layers"]:
        bits.append("edited the layers in the brief")
    oi, ni = old.get("inputs", {}), new.get("inputs", {})
    deps = [f.removeprefix("asset:") for f in ni if f.startswith("asset:") and f in oi and oi[f] != ni[f]]
    if deps:
        bits.append(", ".join(deps) + " re-approved")
    edited = [f for f in ni if f in oi and oi[f] != ni[f] and not f.startswith("asset:")]
    added = [f for f in ni if f not in oi]
    removed = [f for f in oi if f not in ni]
    if edited:
        bits.append("edited " + ", ".join(edited))
    if added:
        bits.append("now uses " + ", ".join(added))
    if removed:
        bits.append("no longer uses " + ", ".join(removed))
    ot, nt = old.get("tokens", {}), new.get("tokens", {})
    tok = [f"{k} {ot[k]}→{v}" for k, v in nt.items() if k in ot and ot[k] != v]
    tok += [f"+{k}" for k in nt if k not in ot] + [f"-{k}" for k in ot if k not in nt]
    if tok:
        bits.append("tokens " + ", ".join(tok))
    op, np_ = old.get("params", {}), new.get("params", {})
    par = [f"{k}={v}" for k, v in np_.items() if op.get(k) != v] + [f"-{k}" for k in op if k not in np_]
    if par:
        bits.append("params " + ", ".join(par))
    if not bits and old.get("builder") != new.get("builder"):
        bits.append(f"builder {old.get('builder')}→{new.get('builder')}")
    return "; ".join(bits) or "recipe output changed"
