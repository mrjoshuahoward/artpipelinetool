"""Placement targets (spec §7): staging install notes, Xcode asset catalogs, Godot, Phaser."""
from __future__ import annotations

import json

import pytest

from artpipeline import errors as E
from artpipeline.errors import PipelineError
from conftest import approve, make_manifest


def _ready(make_pipeline, good_png, n=2, renditions=None, **cls):
    """A pipeline with heroes approved, the style locked by the user, every asset approved."""
    m = make_manifest(n_assets=n, heroes=min(n, 2))
    if renditions:
        m["classes"]["badge"]["renditions"] = renditions
    m["classes"]["badge"].update(cls)
    p = make_pipeline(m)
    for i in range(n):
        approve(p, f"badge_{i:02d}", good_png, by="user")
        if i == min(n, 2) - 1:
            p.lock_style("user")
    return p


def test_staging_writes_install_notes(make_pipeline, good_png, project, tmp_path):
    p = _ready(make_pipeline, good_png)
    game = tmp_path / "game"
    game.mkdir()
    out = p.place("staging", project_dir=game)
    assert out["placed"] == 2 and out["install"] == "ART-INSTALL.md"
    notes = (project / "ART-INSTALL.md").read_text()
    assert "'badges/badge_00.png'" in notes and f"'{game}/'" in notes
    assert not (game / "badges").exists()  # staging never writes into the project


def test_xcassets_imagesets(make_pipeline, good_png, project, tmp_path):
    p = _ready(make_pipeline, good_png, renditions=[{"suffix": "@1x", "scale": 0.5}, {"suffix": "@2x", "scale": 1}])
    app = tmp_path / "ios" / "App"
    cat = app / "Assets.xcassets"
    (cat / "badge_01.imageset").mkdir(parents=True)
    (cat / "badge_01.imageset" / "old.png").write_bytes(b"someone else's file")
    (cat / "Contents.json").write_text("{}")
    (tmp_path / "ios" / "DerivedData" / "x" / "Other.xcassets").mkdir(parents=True)  # ignored

    out = p.place("xcassets", project_dir=tmp_path / "ios")
    assert out["catalog"] == "App/Assets.xcassets"
    s0 = cat / "badge_00.imageset"
    doc = json.loads((s0 / "Contents.json").read_text())
    assert [(i["filename"], i["scale"]) for i in doc["images"]] == [("badge_00@1x.png", "1x"),
                                                                     ("badge_00@2x.png", "2x")]
    assert (s0 / "badge_00@2x.png").is_file() and not (s0 / "badge_00.png").exists()
    # a stray file in a set the pipeline now owns is moved aside, not deleted
    assert out["superseded"][0]["was"].endswith("badge_01.imageset/old.png")
    assert not (cat / "badge_01.imageset" / "old.png").exists()
    m = json.loads((project / "art-manifest.json").read_text())
    assert any(f.endswith("Contents.json") for f in m["assets"][0]["approved"]["placed"]["xcassets"])

    # placing again is a no-op: the pipeline recognises its own files
    again = p.place("xcassets", project_dir=tmp_path / "ios")
    assert "superseded" not in again


def test_xcassets_app_icon_and_store_only_classes(good_png, tmp_path, clock):
    from conftest import make_png, write_brief
    from artpipeline.pipeline import Pipeline
    m = make_manifest(n_assets=3, heroes=0)
    m["assets"][0]["class"] = "ios_app_icon_flat"
    m["assets"][0]["destination"] = "icon/app-icon.png"
    m["assets"][1]["class"] = "game_center_badge"
    m["assets"][1]["overrides"] = {"master": [64, 64]}
    m["assets"][2]["class"] = "ios_app_icon_flat"
    m["assets"][2]["overrides"] = {"master": [64, 64]}
    project = tmp_path / "project"
    project.mkdir()
    p, _ = Pipeline.init(write_brief(project / "brief.md", m), clock=clock)
    approve(p, "badge_00", make_png(tmp_path / "icon.png", size=(1024, 1024)))
    approve(p, "badge_01", good_png)
    approve(p, "badge_02", good_png)
    cat = tmp_path / "x" / "A.xcassets"
    (cat / "AppIcon.appiconset").mkdir(parents=True)
    (cat / "AppIcon.appiconset" / "AppIcon-512@2x.png").write_bytes(b"old icon")

    out = p.place("xcassets", project_dir=tmp_path / "x", asset_ids=["badge_00", "badge_01"])
    doc = json.loads((cat / "AppIcon.appiconset" / "Contents.json").read_text())
    assert doc["images"] == [{"filename": "AppIcon-1024.png", "idiom": "universal", "platform": "ios",
                              "size": "1024x1024"}]
    assert out["superseded"][0]["was"].endswith("AppIcon.appiconset/AppIcon-512@2x.png")
    assert "App Store Connect" in out["skipped"][0]["reason"]

    out = p.place("xcassets", project_dir=tmp_path / "x", asset_ids=["badge_02"])
    assert "1024x1024" in out["skipped"][0]["reason"] and out["placed"] == 0


def test_engine_placement_refused_under_provisional_lock(make_pipeline, good_png, tmp_path):
    p = make_pipeline(make_manifest(n_assets=3, heroes=2))
    approve(p, "badge_00", good_png)
    approve(p, "badge_01", good_png)
    p.lock_style("agent", provisional=True)
    (tmp_path / "g").mkdir()
    (tmp_path / "g" / "project.godot").write_text("")
    with pytest.raises(PipelineError) as e:
        p.place("godot", project_dir=tmp_path / "g")
    assert e.value.code == E.USER_SIGNOFF_REQUIRED
    assert p.place("staging")["placed"] == 2


def test_godot_files_and_import_presets(make_pipeline, good_png, project, tmp_path):
    p = _ready(make_pipeline, good_png)
    g = tmp_path / "g"
    (g / "badges").mkdir(parents=True)
    (g / "project.godot").write_text("")
    (g / "badges" / "badge_01.png.import").write_text("user settings")
    out = p.place("godot", project_dir=g)
    assert out["res_paths"]["badge_00"] == "res://badges/badge_00.png"
    imp = (g / "badges" / "badge_00.png.import").read_text()
    assert 'importer="texture"' in imp and "mipmaps/generate=false" in imp
    assert (g / "badges" / "badge_01.png.import").read_text() == "user settings"
    assert any(k.endswith("badge_01.png.import") for k in out["left_alone"])

    with pytest.raises(PipelineError) as e:
        p.place("godot", project_dir=project)  # no project.godot
    assert e.value.code == E.INVALID_ARGUMENT


def test_phaser_pack_merges(make_pipeline, good_png, tmp_path):
    p = _ready(make_pipeline, good_png, renditions=[{"suffix": "-32", "size": [32, 32]}])
    web = tmp_path / "web"
    (web / "public").mkdir(parents=True)
    pack = web / "public" / "artpipeline-pack.json"
    pack.write_text(json.dumps({"other": {"files": []},
                                "artpipeline": {"files": [{"type": "image", "key": "logo", "url": "logo.png"}]}}))
    first = p.place("phaser", asset_ids=["badge_00"], project_dir=web)
    # destinations aren't under public/, so the files are written but can't be loaded by URL
    assert any("outside the web root" in n for n in first["notes"])
    # the hand-written pack is kept in superseded/ before the pipeline first rewrites it
    assert first["superseded"][0]["was"] == str(pack)
    out = p.place("phaser", asset_ids=["badge_00"], project_dir=web, web_root=".", pack="public/artpipeline-pack.json")
    doc = json.loads(pack.read_text())
    assert "other" in doc
    keys = {f["key"]: f["url"] for f in doc["artpipeline"]["files"]}
    assert keys == {"logo": "logo.png", "badge_00": "badges/badge_00.png", "badge_00-32": "badges/badge_00-32.png"}
    assert out.get("superseded") is None  # now it's the pipeline's own file
    assert 'this.load.pack("artpipeline"' in out["load"]


def test_unknown_target_and_nothing_approved(make_pipeline):
    p = make_pipeline()
    with pytest.raises(PipelineError) as e:
        p.place("unity")
    assert e.value.code == E.INVALID_ARGUMENT
    with pytest.raises(PipelineError) as e:
        p.place("staging")
    assert e.value.code == E.INVALID_STATE
