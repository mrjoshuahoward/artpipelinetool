"""2.1 B2: text drawn as outlines (<ap:text>) and `compose` recipes — layout, compiler, schema, pipeline."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from artpipeline import errors as E
from artpipeline.build import BuildError, compile_recipe, describe_change
from artpipeline.build.text import layout, load_font
from artpipeline.imaging.render import render_svg
from artpipeline.pipeline import Pipeline
from artpipeline.schema import BriefManifest
from conftest import make_manifest, make_png
from test_build import TOKENS, write


def make_font(path: Path, kern_av: int = -200) -> Path:
    """A tiny TrueType font built on the fly: square-ish glyphs for A B V I and space, with
    GPOS pair kerning A→V. 1000 units per em, every glyph 600 wide."""
    from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    names = [".notdef", "space", "A", "B", "V", "I"]
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({32: "space", 65: "A", 66: "B", 86: "V", 73: "I"})
    glyphs = {}
    for n in names:
        pen = TTGlyphPen(None)
        if n not in ("space", ".notdef"):
            w = 200 if n == "I" else 500
            pen.moveTo((50, 0)); pen.lineTo((50, 700)); pen.lineTo((50 + w, 700)); pen.lineTo((50 + w, 0))
            pen.closePath()
        glyphs[n] = pen.glyph()
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({n: (600, 50) for n in names})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "Test", "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, sCapHeight=700, usWinAscent=800, usWinDescent=200)
    fb.setupPost()
    addOpenTypeFeaturesFromString(fb.font, f"feature kern {{ pos A V {kern_av}; }} kern;")
    path.parent.mkdir(parents=True, exist_ok=True)
    fb.save(str(path))
    return path


@pytest.fixture
def font(tmp_path) -> Path:
    return make_font(tmp_path / "fonts" / "T.ttf")


# ---------------------------------------------------------------- layout

def test_layout_kerning_anchor_wrap_and_shrink(font):
    f = load_font(font)
    assert f.pairs[("A", "V")] == -200 and f.cap_height == 700
    av = layout(f, ["AV"], size=100)
    ab = layout(f, ["AB"], size=100)
    assert ab.width == pytest.approx(120) and av.width == pytest.approx(100)  # 600+600, minus 200 kern
    mid = layout(f, ["AB"], size=100, x=500, y=100, anchor="middle")
    assert mid.d.startswith("M445 100")  # pen starts at 500 - 60, glyph lsb 5
    top = layout(f, ["A"], size=100, y=0, valign="top")
    assert top.top == pytest.approx(0) and top.bottom == pytest.approx(70)
    wrapped = layout(f, ["AB AB AB"], size=100, max_width=310)  # "AB AB" is 300 wide
    assert wrapped.lines == ["AB AB", "AB"]
    shrunk = layout(f, ["ABABAB"], size=100, max_width=180, fit="shrink")
    assert shrunk.lines == ["ABABAB"] and shrunk.width <= 180 and shrunk.font_size == pytest.approx(50)


def test_missing_glyphs_and_bad_options_are_errors(font):
    from artpipeline.build.text import TextError

    f = load_font(font)
    with pytest.raises(TextError, match="no glyph for 'Zé'"):
        layout(f, ["AZéZ"], size=10)
    with pytest.raises(TextError, match="text-anchor"):
        layout(f, ["A"], size=10, anchor="left")
    with pytest.raises(TextError, match="not a variable font"):
        load_font(font, axes={"wght": 700})


# ---------------------------------------------------------------- <ap:text> in svg recipes

def test_ap_text_becomes_outlines(tmp_path, font):
    write(tmp_path, "art/t.svg", '<ap:text font="../fonts/T.ttf" font-size="20" x="32" y="40" text-anchor="middle" '
                                 'fill="{{tokens.gold}}" stroke="{{tokens.ink}}">{{params.label}}<ap:br/>I</ap:text>')
    c = compile_recipe(tmp_path, {"source": "art/t.svg", "params": {"label": "AB"}}, tokens=TOKENS,
                       asset={"id": "a"}, master=(64, 64))
    svg = c.svg.decode()
    assert "<text" not in svg and "ap:" not in svg and "font-path" not in svg
    assert '<path d="M' in svg and 'fill="#F2C14E"' in svg and 'stroke="#23282B"' in svg
    assert 'aria-label="AB / I"' in svg
    assert set(c.inputs) == {"art/t.svg", "fonts/T.ttf"}

    # The fingerprint covers the drawn output: a font edit only matters where it changes the outlines.
    before = compile_recipe(tmp_path, {"source": "art/t.svg", "params": {"label": "AV"}}, tokens=TOKENS,
                            asset={"id": "a"}, master=(64, 64))
    make_font(font, kern_av=-100)
    after_ab = compile_recipe(tmp_path, {"source": "art/t.svg", "params": {"label": "AB"}}, tokens=TOKENS,
                              asset={"id": "a"}, master=(64, 64))
    assert after_ab.fingerprint == c.fingerprint
    after = compile_recipe(tmp_path, {"source": "art/t.svg", "params": {"label": "AV"}}, tokens=TOKENS,
                           asset={"id": "a"}, master=(64, 64))
    assert after.fingerprint != before.fingerprint
    assert describe_change(before.record(), after.record()) == "edited fonts/T.ttf"


def test_plain_text_and_fontless_text_are_refused(tmp_path, font):
    write(tmp_path, "a.svg", "<text x='1' y='10'>Hi</text>")
    with pytest.raises(BuildError, match="plain <text>"):
        compile_recipe(tmp_path, {"source": "a.svg"}, tokens={}, asset={"id": "a"}, master=(64, 64))
    write(tmp_path, "b.svg", "<ap:text font-size='10'>A</ap:text>")
    with pytest.raises(BuildError, match="needs font="):
        compile_recipe(tmp_path, {"source": "b.svg"}, tokens={}, asset={"id": "a"}, master=(64, 64))
    write(tmp_path, "c.svg", "<ap:text font='fonts/T.ttf' font-size='10'>A<g/></ap:text>")
    with pytest.raises(BuildError, match="only contain text"):
        compile_recipe(tmp_path, {"source": "c.svg"}, tokens={}, asset={"id": "a"}, master=(64, 64))
    write(tmp_path, "d.svg", "<ap:text font='fonts/Missing.ttf' font-size='10'>A</ap:text>")
    with pytest.raises(BuildError, match="font not found"):
        compile_recipe(tmp_path, {"source": "d.svg"}, tokens={}, asset={"id": "a"}, master=(64, 64))


# ---------------------------------------------------------------- compose compiler

def _compose(root, layers, background=None, params=None, assets=None, master=(64, 64)):
    return compile_recipe(root, {"kind": "compose", "layers": layers, "background": background,
                                 "params": params or {}}, tokens=TOKENS, asset={"id": "c"}, master=master,
                          assets=assets)


def test_compose_layers_render_in_order(tmp_path, font):
    make_png(tmp_path / "art" / "shot.png", size=(32, 32), color=(0x22, 0xB8, 0xB0))
    write(tmp_path, "art/frame.svg", '<svg viewBox="0 0 10 10"><rect width="10" height="10" fill="{{band}}"/></svg>')
    c = _compose(tmp_path, [
        {"svg": "art/frame.svg", "params": {"band": "$gold"}},
        {"image": "art/shot.png", "at": [16, 16], "size": [32, 32], "radius": 4,
         "shadow": {"dy": 2, "blur": 2}},
        {"fill": "$ink", "at": [0, 56], "size": [64, 8]},
        {"text": "{{params.t}}", "font": "fonts/T.ttf", "font_size": 6, "at": [32, 62], "anchor": "middle",
         "color": "$gold"},
    ], background="$ink", params={"t": "AB"})
    svg = c.svg.decode()
    assert "<text" not in svg and "clipPath" in svg and "feDropShadow" in svg and "data:image/png" in svg
    assert set(c.inputs) == {"art/frame.svg", "art/shot.png", "fonts/T.ttf"}
    assert c.tokens == {"gold": "#F2C14E", "ink": "#23282B"}
    assert c.record()["kind"] == "compose" and c.record()["builder"] == "compose-1"
    f = tmp_path / "out.svg"
    f.write_bytes(c.svg)
    img = render_svg(f, 64, 64).convert("RGB")
    assert img.getpixel((4, 4)) == (0xF2, 0xC1, 0x4E)      # frame layer, band = $gold
    assert img.getpixel((32, 32)) == (0x22, 0xB8, 0xB0)    # image layer on top
    assert img.getpixel((2, 60)) == (0x23, 0x28, 0x2B)     # fill strip
    assert _compose(tmp_path, [{"fill": "$ink"}]).fingerprint == _compose(tmp_path, [{"fill": "$ink"}]).fingerprint


def test_compose_layer_edits_are_described(tmp_path):
    a = _compose(tmp_path, [{"fill": "$ink"}]).record()
    b = _compose(tmp_path, [{"fill": "$ink", "opacity": 0.5}]).record()
    assert describe_change(a, b) == "edited the layers in the brief"


def test_compose_errors(tmp_path):
    with pytest.raises(BuildError, match="undefined token"):
        _compose(tmp_path, [{"fill": "$purple"}])
    with pytest.raises(BuildError, match="image not found"):
        _compose(tmp_path, [{"image": "nope.png"}])
    with pytest.raises(BuildError, match="no resolver"):
        _compose(tmp_path, [{"asset": "x"}])


# ---------------------------------------------------------------- schema

def _compose_brief() -> dict:
    m = make_manifest(n_assets=3, heroes=1)
    m["style"] = {"block": "Flat.", "tokens": dict(TOKENS), "backgrounds": ["#23282B"]}
    m["classes"]["badge"]["checks"] = {"palette_min_share": None}
    for a in m["assets"]:
        a.pop("group")
    m["assets"][0]["build"] = {"source": "art/hero.svg"}
    m["assets"][1]["build"] = {"kind": "compose", "background": "$teal",
                               "layers": [{"asset": "badge_00", "at": [8, 8], "size": [48, 48]}]}
    m["assets"][2]["build"] = {"kind": "compose", "layers": [{"fill": "$ink"}]}
    return m


def test_schema_compose_rules():
    m = BriefManifest.model_validate(_compose_brief())
    assert m.assets[1].build.layers[0].kind == "asset"

    def bad(mut, match):
        b = _compose_brief()
        mut(b)
        with pytest.raises(ValueError, match=match):
            BriefManifest.model_validate(b)

    bad(lambda b: b["assets"][2]["build"]["layers"][0].update(text="A"), "exactly one of")
    bad(lambda b: b["assets"][2]["build"]["layers"].append({"text": "A"}), "needs font")
    bad(lambda b: b["assets"][2]["build"].update(layers=[]), "at least one layer")
    bad(lambda b: b["assets"][2]["build"].update(source="x.svg"), "not source/template")
    bad(lambda b: b["assets"][0]["build"].update(layers=[{"fill": "$ink"}]), "belong to kind 'compose'")
    bad(lambda b: b["assets"][1]["build"]["layers"].append({"asset": "ghost"}), "not in the brief")
    bad(lambda b: b["assets"][0].update(build={"kind": "compose", "layers": [{"asset": "badge_01"}]}),
        "contains itself")
    bad(lambda b: b["assets"][2]["build"]["layers"][0].update(fill="red"), "fill")


# ---------------------------------------------------------------- pipeline

@pytest.fixture
def cp(project, make_pipeline) -> Pipeline:
    write(project, "art/hero.svg", '<rect width="64" height="64" fill="{{tokens.gold}}"/>')
    return make_pipeline(_compose_brief())


def test_asset_layers_need_approved_art_and_track_it(cp, project):
    cp.build("main", ["badge_00"])
    cp.review_sheet(["badge_00"])
    cp.decide("badge_00", "approve", "user")
    cp.lock_style("user")
    early = cp.build("main", ["badge_01", "badge_02"])["results"]
    assert [r["status"] for r in early] == ["awaiting_review", "awaiting_review"]
    att = cp.status("badge_01")["attempts"][0]
    assert set(att["build"]["inputs"]) == {"asset:badge_00"}
    assert att["provenance"]["tool"] == "artpipeline build (compose)"
    img = Image.open(project / att["processed"]).convert("RGB")
    assert img.getpixel((2, 2)) == (0x22, 0xB8, 0xB0)      # $teal background
    assert img.getpixel((32, 32)) == (0xF2, 0xC1, 0x4E)    # the approved hero, embedded
    cp.review_sheet(["badge_01"])
    cp.decide("badge_01", "approve", "agent")

    # A token change reopens the hero; until it is approved again, badge_01 can't rebuild from it.
    lock = cp.lock_style("user", tokens={**TOKENS, "gold": "#F5C451"})
    assert "badge_00" in lock["stale"]
    out = cp.build("main", stale=True)
    by = {r["asset_id"]: r for r in out["results"]}
    assert by["badge_00"]["status"] == "awaiting_review"
    assert "badge_01" not in by or by["badge_01"].get("error") == E.BUILD_FAILED
    blocked = cp.build("main", ["badge_01"])["results"][0]
    assert blocked["error"] == E.BUILD_FAILED and "approve that asset first" in blocked["message"]

    cp.review_sheet(["badge_00"])
    cp.decide("badge_00", "approve", "user")
    assert "badge_01" in cp.status()["recipes"]["stale"]
    again = cp.build("main", ["badge_01"])["results"][0]
    assert again["status"] == "awaiting_review" and again["change"] == "rebuilt: badge_00 re-approved"
