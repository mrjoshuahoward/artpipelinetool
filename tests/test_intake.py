from __future__ import annotations

import pytest

from artpipeline import errors as E
from artpipeline.errors import PipelineError
from artpipeline.intake import load_brief, parse_manifest
from conftest import make_manifest, write_brief


def test_markdown_brief(tmp_path):
    m = load_brief(write_brief(tmp_path / "b.md", make_manifest()))
    assert m.project == "Sorting Line"
    assert len(m.assets) == 4
    assert m.resolve_class(m.assets[0]).master == (64, 64)


def test_yaml_brief(tmp_path):
    m = load_brief(write_brief(tmp_path / "b.yaml", make_manifest(), markdown=False))
    assert m.assets[0].class_ == "badge"


def test_missing_section(tmp_path):
    (tmp_path / "b.md").write_text("# Just prose\n", encoding="utf-8")
    with pytest.raises(PipelineError) as e:
        load_brief(tmp_path / "b.md")
    assert e.value.code == E.BRIEF_NO_MANIFEST


def test_missing_file(tmp_path):
    with pytest.raises(PipelineError) as e:
        load_brief(tmp_path / "nope.md")
    assert e.value.code == E.BRIEF_NOT_FOUND


def test_v1_manifest_rejected():
    with pytest.raises(PipelineError) as e:
        parse_manifest({"project": "Matador", "direction": "X", "assets": [{"id": "bird_crane"}]})
    assert e.value.code == E.BRIEF_VERSION


def test_problems_are_listed():
    m = make_manifest()
    m["assets"][0]["destination"] = "../escape.png"
    del m["assets"][1]["subject"]
    with pytest.raises(PipelineError) as e:
        parse_manifest(m)
    assert e.value.code == E.BRIEF_INVALID
    where = [p["at"] for p in e.value.details["problems"]]
    assert "assets.0.destination" in where and "assets.1.subject" in where


@pytest.mark.parametrize("mutate,needle", [
    (lambda m: m["assets"][1].update(id="badge_00"), "duplicate asset id"),
    (lambda m: m["assets"][1].update(destination="badges/badge_00.png"), "share destination"),
    (lambda m: m["assets"][0].update({"class": "nope"}), "unknown class"),
    (lambda m: m["assets"][0].update(overrides={"alpha": "sometimes"}), "invalid overrides"),
    (lambda m: m["style"].update(palette=["teal"]), "not a #RRGGBB"),
])
def test_consistency_errors(mutate, needle):
    m = make_manifest()
    mutate(m)
    with pytest.raises(PipelineError) as e:
        parse_manifest(m)
    assert needle in str(e.value.details["problems"])


def test_presets_and_overrides():
    m = make_manifest()
    m["assets"][0].update({"class": "sprite", "overrides": {"master": [128, 128], "checks": {"halo": False}}})
    m["assets"][1].update({"class": "game_center_badge"})
    bm = parse_manifest(m)
    sprite = bm.resolve_class(bm.assets[0])
    assert sprite.master == (128, 128) and sprite.alpha == "required" and sprite.checks.halo is False
    assert sprite.checks.greyscale_read is True  # deep merge keeps untouched fields
    assert bm.resolve_class(bm.assets[1]).alpha == "forbidden"


def test_rendition_needs_one_of_scale_or_size():
    m = make_manifest()
    m["classes"]["badge"]["renditions"] = [{"suffix": "@2x"}]
    with pytest.raises(PipelineError):
        parse_manifest(m)
