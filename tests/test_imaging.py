"""Imaging: parity with the skill's scripts (same verdicts and metrics), plus the new behaviour."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from artpipeline.checks import CheckContext, imaging_checker
from artpipeline.cli import run
from artpipeline.imaging.analyze import CheckOptions, analyze
from artpipeline.imaging.process import (
    ProcessError, fit_to_master, palette_clamp, remove_background, resize_rendition, trim,
)
from artpipeline.imaging.render import render_svg
from artpipeline.imaging.sheet import SheetItem, _fit, build_sheets
from artpipeline.schema import AssetClass
from conftest import PROV, make_manifest

SKILL_SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "casual-mobile-art-director" / "scripts"
PALETTE = ["#22B8B0", "#F2C14E", "#23282B"]
BGS = ["#23282B", "#49606B"]
SVG_CIRCLE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
              '<circle cx="50" cy="50" r="40" fill="#F2C14E" stroke="#23282B" stroke-width="6"/></svg>')


def _pixels(img: Image.Image) -> list[tuple[int, ...]]:
    b = img.convert("RGBA").tobytes()
    return [tuple(b[i:i + 4]) for i in range(0, len(b), 4)]


def _skill(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SKILL_SCRIPTS / script), *args],
                          capture_output=True, text=True)


# ------------------------------------------------------------------ fixtures

def badge_png(path: Path) -> Path:
    img = Image.new("RGB", (256, 256), "#22B8B0")
    d = ImageDraw.Draw(img)
    d.ellipse([48, 48, 208, 208], fill="#F2C14E", outline="#23282B", width=10)
    img.save(path)
    return path


def haloed_sprite(path: Path) -> Path:
    """Dark sprite whose anti-aliased edge is near-white: the matte fringe of a bad bg removal."""
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([40, 40, 216, 216], fill=(240, 240, 240, 120))
    d.ellipse([46, 46, 210, 210], fill=(35, 40, 43, 255))
    img.save(path)
    return path


def noisy_png(path: Path) -> Path:
    img = Image.new("RGB", (256, 256))
    img.putdata([((x * 7) % 256, (y * 5) % 256, ((x + y) * 3) % 256) for y in range(256) for x in range(256)])
    img.save(path)
    return path


# ------------------------------------------------------------------ parity with the skill's scripts

@pytest.mark.parametrize("maker,flags", [
    (badge_png, ["--no-alpha", "--size", "256x256"]),
    (haloed_sprite, ["--expect-alpha"]),
    (noisy_png, ["--no-alpha"]),
])
def test_check_parity_with_skill(tmp_path, maker, flags):
    f = maker(tmp_path / "a.png")
    skill = _skill("check_asset.py", str(f), "--palette", ",".join(PALETTE), "--bg", ",".join(BGS), *flags)
    ref = json.loads(skill.stdout)[0]

    alpha = "forbidden" if "--no-alpha" in flags else "required"
    size = (256, 256) if "--size" in flags else None
    ours = analyze(Image.open(f), CheckOptions(size=size, alpha=alpha, palette=PALETTE, backgrounds=BGS,
                                               greyscale_read=False))
    assert ours.passed == ref["pass"]
    assert bool(ours.fail) == bool(ref["fail"]) and len(ours.fail) == len(ref["fail"])
    assert ours.metrics.get("mean_rgb") == ref.get("mean_rgb")
    assert ("halo_ratio" in ours.metrics) == ("halo_ratio" in ref)  # value differs by design
    assert ours.metrics.get("palette") == ref.get("palette")
    assert ours.metrics.get("contrast") == ref.get("contrast")
    assert len(ours.warn) == len(ref["warn"])


def keylined_icon(path: Path) -> Path:
    """Light icon with a dark keyline, anti-aliased, at 44 px: a normal, healthy UI icon @1x."""
    svg = path.with_suffix(".svg")
    svg.write_text(SVG_CIRCLE)
    render_svg(svg, 44).save(path)
    return path


def test_halo_keyline_false_positive_fixed(tmp_path):
    f = keylined_icon(tmp_path / "k.png")
    ref = json.loads(_skill("check_asset.py", str(f), "--expect-alpha").stdout)[0]
    # The skill's global-mean heuristic: at small sizes the light fill dominates the mean, so
    # the whole anti-aliased keyline reads as "off-tone".
    assert ref["pass"] is False and "halo" in ref["fail"][0]
    ours = analyze(Image.open(f), CheckOptions(alpha="required"))
    assert ours.passed and ours.metrics["halo_ratio"] < 0.12
    # ...while a real matte fringe still fails.
    bad = analyze(Image.open(haloed_sprite(tmp_path / "h.png")), CheckOptions(alpha="required"))
    assert not bad.passed and "halo" in bad.fail[0]


def test_clamp_parity_with_skill(tmp_path):
    src = noisy_png(tmp_path / "src.png")
    _skill("palette_clamp.py", str(src), str(tmp_path / "ref.png"), "--palette", ",".join(PALETTE))
    ref = _pixels(Image.open(tmp_path / "ref.png"))
    ours = _pixels(palette_clamp(Image.open(src), PALETTE))
    differing = sum(a != b for a, b in zip(ref, ours)) / len(ref)
    # The skill caches by 6-bit-quantised colour (first pixel in a bucket wins); we cache exact
    # colours. Only pixels sitting on a palette boundary can differ.
    assert differing < 0.02
    assert set(ours) <= {(*tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)), 255) for h in PALETTE}


def test_export_parity_with_skill(tmp_path):
    src = badge_png(tmp_path / "m.png")
    _skill("export_sizes.py", str(src), str(tmp_path / "out"), "--name", "b", "--px", "64")
    ref = Image.open(tmp_path / "out" / "b-64.png").convert("RGBA")
    ours = resize_rendition(Image.open(src).convert("RGBA"), (64, 64), pixel_art=False)
    assert ref.tobytes() == ours.tobytes()


# ------------------------------------------------------------------ processing

def test_remove_background_keeps_enclosed_regions(tmp_path):
    img = Image.new("RGB", (200, 200), (255, 0, 255))  # chroma magenta backdrop
    d = ImageDraw.Draw(img)
    d.ellipse([30, 30, 170, 170], fill=(34, 184, 176))
    d.ellipse([90, 90, 110, 110], fill=(255, 0, 255))  # same colour, but enclosed: must survive
    out = remove_background(img)
    a = out.getchannel("A")
    assert a.getpixel((0, 0)) == 0 and a.getpixel((199, 199)) == 0
    assert a.getpixel((100, 100)) == 255 and a.getpixel((60, 100)) == 255


def test_fit_rules():
    big = Image.new("RGBA", (128, 128), (1, 2, 3, 255))
    assert fit_to_master(big, (64, 64), pixel_art=False, pad=False).size == (64, 64)
    with pytest.raises(ProcessError, match="aspect"):
        fit_to_master(Image.new("RGBA", (128, 100)), (64, 64), pixel_art=False, pad=False)
    with pytest.raises(ProcessError, match="smaller than master"):
        fit_to_master(Image.new("RGBA", (32, 32)), (64, 64), pixel_art=False, pad=False)
    with pytest.raises(ProcessError, match="integer multiple"):
        fit_to_master(Image.new("RGBA", (96, 96)), (64, 64), pixel_art=True, pad=False)
    tall = Image.new("RGBA", (40, 80), (9, 9, 9, 255))
    padded = fit_to_master(trim(tall), (64, 64), pixel_art=False, pad=True)
    assert padded.size == (64, 64) and padded.getchannel("A").getbbox() == (16, 0, 48, 64)


def test_rendition_refuses_upscale():
    with pytest.raises(ProcessError):
        resize_rendition(Image.new("RGBA", (64, 64)), (128, 128), pixel_art=False)


def test_svg_renders_at_any_size(tmp_path):
    svg = tmp_path / "c.svg"
    svg.write_text(SVG_CIRCLE)
    for s in (24, 256, 1024):
        img = render_svg(svg, s)
        assert img.size == (s, s)
        assert img.getpixel((s // 2, s // 2))[:3] == (0xF2, 0xC1, 0x4E)
        assert img.getpixel((0, 0))[3] == 0


def test_greyscale_read_warns_on_hue_only_contrast():
    img = Image.new("RGB", (100, 100), (220, 40, 40))
    ImageDraw.Draw(img).rectangle([50, 0, 99, 99], fill=(40, 132, 40))  # same L* as the red
    f = analyze(img, CheckOptions())
    assert any("differ mostly in hue" in w for w in f.warn)
    assert not any("hue" in w for w in analyze(Image.new("RGB", (100, 100), "#22B8B0"), CheckOptions()).warn)


def test_checker_svg_source_for_raster_class_with_flatten(tmp_path):
    svg = tmp_path / "badge.svg"
    svg.write_text(SVG_CIRCLE)
    cls = AssetClass(format="png", master=(512, 512), alpha="forbidden",
                     processing={"flatten": "#22B8B0", "palette_clamp": "hard"},
                     renditions=[{"suffix": "@small", "size": (64, 64)}])
    res = imaging_checker(svg, cls, CheckContext(PALETTE, BGS, tmp_path / "out", "badge"))
    assert res.passed, res.fail
    assert Image.open(res.processed_path).size == (512, 512)
    assert Image.open(res.renditions["@small"]).size == (64, 64)
    assert res.metrics["palette"]["in_palette_share"] == 1.0


def test_checker_halo_fails(tmp_path):
    f = haloed_sprite(tmp_path / "s.png")
    cls = AssetClass(format="png", master=(256, 256), alpha="required")
    res = imaging_checker(f, cls, CheckContext([], [], tmp_path / "out", "s"))
    assert not res.passed and "halo" in res.fail[0]


# ------------------------------------------------------------------ contact sheets

def test_sheet_keeps_aspect_and_pixel_crispness():
    assert _fit(Image.new("RGBA", (1320, 2868)), 400, False).size == (184, 400)
    px = Image.new("RGBA", (4, 4), (255, 0, 0, 255))
    px.putpixel((0, 0), (0, 0, 255, 255))
    up = _fit(px, 64, True)
    assert len(set(_pixels(up))) == 2  # nearest-neighbour: no blended colours


def test_sheet_paginates(tmp_path):
    items = [SheetItem(label=f"a{i}", image=Image.new("RGBA", (64, 64), (9, 9, 9, 255)), sizes=[64, 24])
             for i in range(13)]
    pages = build_sheets(items, tmp_path, "s", "Review")
    assert [p.name for p in pages] == ["s-p1.png", "s-p2.png"]


def test_review_sheet_in_pipeline(make_pipeline, good_png):
    m = make_manifest(n_assets=3, heroes=0)
    m["settings"]["gate_threshold"] = 2
    p = make_pipeline(m)
    p.claim("main", n=2)
    for aid in ("badge_00", "badge_01"):
        p.register_attempt(aid, good_png, "main", PROV)
    sheet = p.review_sheet(pending_review=True)
    assert [i[0] for i in sheet["items"]] == ["badge_00", "badge_01"]
    assert all(Path(x).is_file() for x in sheet["pages"])
    p.decide("badge_00", "approve", "agent")
    gate = p.decide("badge_01", "approve", "agent")["gate_due"]
    gs = p.review_sheet(gate_id=gate["gate_id"])
    assert "pass_gate" in gs["next"]
    assert p.pass_gate(gate["gate_id"], "user")["passed"]


# ------------------------------------------------------------------ stateless CLI

def test_cli_check_process_sheet(tmp_path):
    f = badge_png(tmp_path / "b.png")
    code, out = run(["check", str(f), "--class", "game_center_badge"])
    assert code == 1 and "size 256x256 != 1024x1024" in out[0]["fail"]
    code, out = run(["check", str(f), "--size", "256x256", "--alpha", "forbidden",
                     "--palette", ",".join(PALETTE)])
    assert code == 0 and out[0]["pass"]

    svg = tmp_path / "icon.svg"
    svg.write_text(SVG_CIRCLE)
    code, out = run(["process", str(svg), str(tmp_path / "out"), "--size", "44x44", "--alpha", "required",
                     "--scales", "1,2,3"])
    assert code == 0, out
    assert sorted(out["renditions"]) == ["@1x", "@2x", "@3x"]
    assert Image.open(out["renditions"]["@3x"]).size == (132, 132)

    code, out = run(["contact-sheet", str(tmp_path / "sheet.png"), str(f), str(svg), "--sizes", "128,32"])
    assert code == 0 and Path(out["pages"][0]).is_file()
