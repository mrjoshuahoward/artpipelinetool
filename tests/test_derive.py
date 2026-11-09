"""2.1 B3: `derive` recipes — sprite sheets and texture atlases from approved assets, and placing them."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from artpipeline import errors as E
from artpipeline.build import BuildError, compile_recipe, describe_change
from artpipeline.pipeline import Pipeline
from artpipeline.schema import BriefManifest
from test_build import TOKENS, write


def sprite(path: Path, size=(32, 32), box=(8, 4, 24, 28), color=(0xF2, 0xC1, 0x4E, 255)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), color), box[:2])
    img.save(path)
    return path


def derive(tmp_path, files: dict[str, Path], master=(128, 64), **build):
    b = {"kind": "derive", "frames": list(files), **build}
    return compile_recipe(tmp_path, b, tokens={}, asset={"id": "sheet"}, master=master,
                          assets=lambda aid: files[aid] if aid in files else (_ for _ in ()).throw(
                              BuildError(f"layer asset '{aid}' is pending")))


# ---------------------------------------------------------------- compiler

def test_grid_sheet_centres_frames_in_cells(tmp_path):
    files = {f"f{i}": sprite(tmp_path / f"f{i}.png") for i in range(3)}
    c = derive(tmp_path, files, layout="grid", padding=0, animation={"fps": 8, "sequence": ["f0", "f1", "f2", "f1"]})
    a = c.record()["atlas"]
    assert a["cell"] == [32, 32] and a["order"] == ["f0", "f1", "f2"]
    assert a["frames"]["f1"] == {"x": 32, "y": 0, "w": 32, "h": 32, "source_w": 32, "source_h": 32,
                                 "trim_x": 0, "trim_y": 0}
    assert a["animation"] == {"fps": 8.0, "loop": True, "sequence": ["f0", "f1", "f2", "f1"]}
    assert c.ext == ".png" and c.record()["kind"] == "derive"
    import io
    img = Image.open(io.BytesIO(c.svg))
    assert img.size == (128, 64)
    assert img.getpixel((32 + 10, 10))[3] == 255 and img.getpixel((32 + 2, 2))[3] == 0


def test_pack_trims_and_extrudes(tmp_path):
    files = {"big": sprite(tmp_path / "big.png", box=(0, 0, 32, 32)), "small": sprite(tmp_path / "s.png")}
    c = derive(tmp_path, files, padding=2, extrude=1)
    fr = c.record()["atlas"]["frames"]
    assert fr["big"]["x"] == 1 and fr["big"]["y"] == 1            # extrude margin from the edge
    assert fr["small"] == {"x": 1 + 32 + 2 + 2, "y": 1, "w": 16, "h": 24, "source_w": 32, "source_h": 32,
                           "trim_x": 8, "trim_y": 4}
    import io
    img = Image.open(io.BytesIO(c.svg))
    assert img.getpixel((0, 0))[3] == 255                         # the extruded corner
    assert img.getpixel((34, 5))[3] == 0                          # the padding stays clear


def test_derive_errors_and_staleness(tmp_path):
    files = {f"f{i}": sprite(tmp_path / f"f{i}.png") for i in range(5)}
    with pytest.raises(BuildError, match="need 160x32; the class master is 128x64"):
        derive(tmp_path, files, layout="grid", columns=5, padding=0)
    with pytest.raises(BuildError, match="don't fit"):
        derive(tmp_path, files, master=(40, 40))
    with pytest.raises(BuildError, match="pending"):
        derive(tmp_path, {"f0": files["f0"]}, frames=["f0", "missing"])
    vec = write(tmp_path, "v.svg", '<svg viewBox="0 0 10 10"><rect width="10" height="10"/></svg>')
    with pytest.raises(BuildError, match="set cell"):
        derive(tmp_path, {"v": vec})
    one = {"f0": files["f0"]}
    a = derive(tmp_path, one)
    assert a.fingerprint == derive(tmp_path, one).fingerprint
    sprite(files["f0"], box=(4, 4, 28, 28))
    b = derive(tmp_path, one)
    assert b.fingerprint != a.fingerprint and describe_change(a.record(), b.record()) == "f0 re-approved"


# ---------------------------------------------------------------- schema

def _brief() -> dict:
    return {
        "version": 2, "project": "Demo", "direction": "Flat",
        "style": {"block": "Flat.", "tokens": dict(TOKENS)},
        "classes": {"spr": {"format": "png", "master": [32, 32], "alpha": "required", "display_sizes": [32],
                            "checks": {"palette_min_share": None}},
                    "sheet": {"format": "png", "master": [128, 64], "alpha": "required", "display_sizes": [128],
                              "checks": {"palette_min_share": None}}},
        "groups": {"coin": {"build": {"source": "art/coin.svg"}}},
        "assets": [
            {"id": "coin-0", "class": "spr", "subject": "Coin", "acceptance_criteria": ["ok"],
             "destination": "sprites/coin-0.png", "group": "coin", "hero": True, "build": {"params": {"w": 12}}},
            {"id": "coin-1", "class": "spr", "subject": "Coin", "acceptance_criteria": ["ok"],
             "destination": "sprites/coin-1.png", "group": "coin", "build": {"params": {"w": 6}}},
            {"id": "coin-spin", "class": "sheet", "subject": "Spin", "acceptance_criteria": ["ok"],
             "destination": "sprites/coin-spin.png",
             "build": {"kind": "derive", "layout": "grid", "frames_group": "coin", "padding": 0,
                       "animation": {"fps": 10, "sequence": ["coin-0", "coin-1", "coin-0"]}}},
        ],
    }


def test_schema_derive_rules():
    m = BriefManifest.model_validate(_brief())
    assert m.assets[2].build.frames == ["coin-0", "coin-1"]

    def bad(mut, match):
        b = _brief()
        mut(b)
        with pytest.raises(ValueError, match=match):
            BriefManifest.model_validate(b)

    bad(lambda b: b["assets"][2]["build"].update(frames=["coin-0", "coin-0"], frames_group=None),
        "listed twice")
    bad(lambda b: b["assets"][2]["build"]["animation"].update(sequence=["coin-9"]), "not frames")
    bad(lambda b: b["assets"][2]["build"].update(frames=["coin-0"]), "not both")
    bad(lambda b: b["assets"][2]["build"].update(layout="pack", columns=2), "layout: grid")
    bad(lambda b: b["assets"][0]["build"].update(cell=[8, 8]), "belong to kind 'derive'")
    bad(lambda b: b["assets"][2]["build"].update(frames_group="nobody"), "has no other assets")
    bad(lambda b: b["assets"][2]["build"].update(frames_group=None, frames=["ghost"], animation=None), "not in the brief")


# ---------------------------------------------------------------- pipeline and placement

@pytest.fixture
def dp(project, make_pipeline) -> Pipeline:
    write(project, "art/coin.svg", '<svg viewBox="0 0 32 32"><rect x="10" y="4" width="{{w}}" height="24" '
                                   'fill="{{tokens.gold}}"/></svg>')
    p = make_pipeline(_brief())
    p.build("main", ["coin-0"])
    p.review_sheet(["coin-0"])
    p.decide("coin-0", "approve", "user")
    p.lock_style("user")
    return p


def _approve(p: Pipeline, aid: str) -> dict:
    r = p.build("main", [aid])["results"][0]
    assert r["status"] == "awaiting_review", r
    p.review_sheet([aid])
    p.decide(aid, "approve", "agent")
    return r


def test_sheet_waits_for_frames_then_builds_and_stages(dp, project):
    blocked = dp.build("main", ["coin-spin"])["results"][0]
    assert blocked["error"] == E.BUILD_FAILED and "coin-1" in blocked["message"]
    _approve(dp, "coin-1")
    _approve(dp, "coin-spin")
    att = dp.status("coin-spin")["attempts"][-1]
    assert att["build"]["kind"] == "derive" and set(att["build"]["inputs"]) == {"asset:coin-0", "asset:coin-1"}
    assert att["source"].endswith("source.png")
    staged = json.loads((project / "sprites" / "coin-spin.json").read_text())
    assert staged["meta"]["image"] == "coin-spin.png" and staged["meta"]["size"] == {"w": 128, "h": 64}
    assert staged["frames"]["coin-1"]["frame"] == {"x": 32, "y": 0, "w": 32, "h": 32}
    assert staged["meta"]["animation"]["frames"] == ["coin-0", "coin-1", "coin-0"]
    doc = json.loads((project / "art-manifest.json").read_text())
    entry = next(a for a in doc["assets"] if a["id"] == "coin-spin")["approved"]["build"]
    assert entry["atlas"]["order"] == ["coin-0", "coin-1"]

    # Re-approving a frame makes the sheet stale.
    write(project, "art/coin.svg", (project / "art/coin.svg").read_text().replace('height="24"', 'height="20"'))
    out = dp.build("main", stale=True)
    assert {r["asset_id"] for r in out["results"]} >= {"coin-0", "coin-1"}
    for aid in ("coin-0", "coin-1"):
        dp.review_sheet([aid])
        dp.decide(aid, "approve", "user" if aid == "coin-0" else "agent")
    assert "coin-spin" in dp.status()["recipes"]["stale"]
    again = dp.build("main", ["coin-spin"])["results"][0]
    assert again["change"] == "rebuilt: coin-0, coin-1 re-approved"


def test_atlas_classes_must_not_move_frames(dp, project):
    b = _brief()
    b["classes"]["sheet"]["processing"] = {"trim": True}
    from conftest import write_brief
    write_brief(project / "brief.md", b)
    p, _ = Pipeline.init(project / "brief.md")
    _approve(p, "coin-1")
    r = p.build("main", ["coin-spin"])["results"][0]
    assert r["error"] == E.BUILD_FAILED and "trim" in r["message"]


def test_place_atlases_into_engines(dp, project, tmp_path):
    _approve(dp, "coin-1")
    _approve(dp, "coin-spin")

    gd = tmp_path / "gd"
    gd.mkdir()
    (gd / "project.godot").write_text("config_version=5\n")
    out = dp.place("godot", ["coin-spin"], gd)
    assert out["sprite_frames"]["coin-spin"] == "res://sprites/coin-spin.sprite_frames.tres"
    tres = (gd / "sprites" / "coin-spin_frames" / "coin-1.tres").read_text()
    assert 'path="res://sprites/coin-spin.png"' in tres and "region = Rect2(32, 0, 32, 32)" in tres
    frames = (gd / "sprites" / "coin-spin.sprite_frames.tres").read_text()
    assert frames.count('SubResource("f0")') == 2 and '"speed": 10.0' in frames and "load_steps=4" in frames

    ph = tmp_path / "ph"
    ph.mkdir()
    dp.place("phaser", ["coin-spin"], ph, web_root=".")
    pack = json.loads((ph / "artpipeline-pack.json").read_text())
    assert pack["artpipeline"]["files"] == [{"type": "atlas", "key": "coin-spin", "textureURL": "sprites/coin-spin.png",
                                             "atlasURL": "sprites/coin-spin.json"}]
    assert json.loads((ph / "sprites" / "coin-spin.json").read_text())["meta"]["image"] == "coin-spin.png"

    xc = tmp_path / "xc"
    (xc / "A.xcassets").mkdir(parents=True)
    dp.place("xcassets", ["coin-spin"], xc)
    sa = xc / "A.xcassets" / "coin-spin.spriteatlas"
    assert json.loads((sa / "Contents.json").read_text())["info"]["author"] == "xcode"
    with Image.open(sa / "coin-1.imageset" / "coin-1.png") as im:
        assert im.size == (32, 32)


def test_status_reports_waiting_not_errors(dp, project):
    _approve(dp, "coin-1")
    _approve(dp, "coin-spin")
    write(project, "art/coin.svg", (project / "art/coin.svg").read_text().replace('height="24"', 'height="20"'))
    dp.build("main", ["coin-1"])       # coin-1 is back in review, so the sheet can't compile right now
    rec = dp.status()["recipes"]
    assert rec["waiting"] == {"coin-spin": "coin-1 (awaiting_review)"} and "errors" not in rec
    assert dp.status("coin-spin")["waiting_on"] == "coin-1 (awaiting_review)"


def test_place_waits_for_an_open_gate_but_staging_doesnt(project, make_pipeline, tmp_path):
    from conftest import make_manifest, approve, make_png
    m = make_manifest(n_assets=3, heroes=1)
    m["settings"] = {"gate_threshold": 2}
    p = make_pipeline(m)
    ids = [a["id"] for a in m["assets"]]
    png = make_png(tmp_path / "g.png")
    approve(p, ids[0], png, by="user")
    p.lock_style("user")
    for aid in ids[1:]:
        approve(p, aid, png)
    assert p.status()["open_gate"]
    gd = tmp_path / "gd"
    gd.mkdir()
    (gd / "project.godot").write_text("config_version=5\n")
    from artpipeline.errors import PipelineError
    with pytest.raises(PipelineError) as e:
        p.place("godot", None, gd)
    assert e.value.code == E.GATE_DUE
    assert p.place("staging")["placed"] == 3
