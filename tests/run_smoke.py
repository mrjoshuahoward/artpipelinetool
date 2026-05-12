"""Standalone smoke runner — invokes the key test cases without pytest.

Run from repo root:
    PYTHONPATH=. python3 tests/run_smoke.py
"""
from __future__ import annotations
import copy
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

from click.testing import CliRunner
from PIL import Image

from artpipeline.cli import main

# Inline copies of fixtures from tests/conftest.py (avoids importing pytest at module load).
SAMPLE_BRIEF_YAML = """\
project: TestProject
direction: TestDirection
assets:
  - id: bird_crane
    type: bird_sprite
    species: crane
    destination: art/birds/crane@1x.png
    dimensions: [48, 48]
    prompt: "Top-down silhouette of a Sandhill Crane viewed from above."
    acceptance_criteria:
      - "Silhouette only, no internal detail"
      - "Transparent background"
"""
SAMPLE_BRIEF_TEXT = (
    "# Test Brief\n\nSome prose.\n\n## Asset Manifest\n```yaml\n"
    + SAMPLE_BRIEF_YAML
    + "```\n"
)
SAMPLE_ASSET = {
    "id": "bird_crane",
    "status": "pending",
    "type": "bird_sprite",
    "species": "crane",
    "destination": "art/birds/crane@1x.png",
    "dimensions": [48, 48],
    "prompt": "Top-down silhouette of a Sandhill Crane viewed from above.",
    "acceptance_criteria": ["Silhouette only, no internal detail", "Transparent background"],
    "rejection_reason": None,
    "retry_count": 0,
    "filed_path": None,
    "derived_resolutions": None,
}
SAMPLE_MANIFEST_DATA = {
    "brief": "test-brief.md",
    "project": "TestProject",
    "direction": "TestDirection",
    "assets": {"bird_crane": SAMPLE_ASSET},
}


def _write_pipeline(project, extra=None):
    data = copy.deepcopy(SAMPLE_MANIFEST_DATA)
    if extra:
        data["assets"]["bird_crane"].update(extra)
    (project / "pipeline.json").write_text(json.dumps(data, indent=2))


def _write_brief(project):
    p = project / "test-brief.md"
    p.write_text(SAMPLE_BRIEF_TEXT, encoding="utf-8")
    return p


RESULTS = []


def case(name):
    def wrap(fn):
        def runner():
            project = Path(tempfile.mkdtemp())
            cwd_before = os.getcwd()
            try:
                fn(project)
                RESULTS.append((name, True, ""))
            except Exception:
                RESULTS.append((name, False, traceback.format_exc()))
            finally:
                os.chdir(cwd_before)
        return runner
    return wrap


@case("parse: creates pipeline.json with new assets")
def t_parse_creates(project):
    brief = _write_brief(project)
    r = CliRunner().invoke(main, ["parse", str(brief)], catch_exceptions=False)
    assert r.exit_code == 0, r.output
    data = json.loads((project / "pipeline.json").read_text())
    assert "bird_crane" in data["assets"]


@case("parse: reads transparent_background from YAML")
def t_parse_reads_transparent(project):
    yaml_text = (
        "project: P\n"
        "direction: D\n"
        "assets:\n"
        "  - id: bird_crane\n"
        "    type: bird_sprite\n"
        "    species: crane\n"
        "    destination: art/birds/crane@1x.png\n"
        "    dimensions: [48, 48]\n"
        "    transparent_background: true\n"
        "    prompt: x\n"
        "    acceptance_criteria:\n"
        "      - y\n"
    )
    brief = project / "brief.md"
    brief.write_text("## Asset Manifest\n```yaml\n" + yaml_text + "```\n", encoding="utf-8")
    r = CliRunner().invoke(main, ["parse", str(brief)], catch_exceptions=False)
    assert r.exit_code == 0
    data = json.loads((project / "pipeline.json").read_text())
    assert data["assets"]["bird_crane"]["transparent_background"] is True


@case("file: resizes oversized source to canonical")
def t_resize_oversized(project):
    os.chdir(project)
    _write_pipeline(project)
    src = project / "oversized.png"
    Image.new("RGB", (1024, 1024), (200, 180, 120)).save(src)
    r = CliRunner().invoke(main, ["file", str(src), "bird_crane"], catch_exceptions=False)
    assert r.exit_code == 0, r.output
    with Image.open(project / "art/birds/crane@1x.png") as img:
        assert list(img.size) == [48, 48], img.size


@case("file: preserves alpha when source has alpha")
def t_preserve_alpha(project):
    os.chdir(project)
    _write_pipeline(project)
    src = project / "alpha.png"
    Image.new("RGBA", (200, 200), (100, 50, 50, 200)).save(src)
    r = CliRunner().invoke(main, ["file", str(src), "bird_crane"], catch_exceptions=False)
    assert r.exit_code == 0, r.output
    with Image.open(project / "art/birds/crane@1x.png") as img:
        assert img.mode == "RGBA", img.mode


@case("file: transparent_background=true strips near-white bg")
def t_strips_white(project):
    os.chdir(project)
    _write_pipeline(project, {"transparent_background": True})
    src = project / "flat.png"
    img = Image.new("RGB", (48, 48), (253, 253, 253))
    for y in range(48):
        for x in range(48):
            if 16 <= x < 32 and 16 <= y < 32:
                img.putpixel((x, y), (100, 50, 50))
    img.save(src)
    r = CliRunner().invoke(main, ["file", str(src), "bird_crane"], catch_exceptions=False)
    assert r.exit_code == 0, r.output
    with Image.open(project / "art/birds/crane@1x.png") as out:
        assert out.mode == "RGBA", out.mode
        assert out.getpixel((0, 0))[3] == 0, out.getpixel((0, 0))
        assert out.getpixel((24, 24))[3] == 255, out.getpixel((24, 24))


@case("file: flag absent leaves background opaque")
def t_no_flag_leaves_bg(project):
    os.chdir(project)
    _write_pipeline(project)
    src = project / "flat.png"
    Image.new("RGB", (200, 200), (253, 253, 253)).save(src)
    r = CliRunner().invoke(main, ["file", str(src), "bird_crane"], catch_exceptions=False)
    assert r.exit_code == 0, r.output
    with Image.open(project / "art/birds/crane@1x.png") as out:
        assert out.mode == "RGB", out.mode
        r0, g0, b0 = out.getpixel((0, 0))
        assert r0 > 240 and g0 > 240 and b0 > 240, (r0, g0, b0)


@case("file: fake bytes still work (fallback path)")
def t_fallback_fake_bytes(project):
    os.chdir(project)
    _write_pipeline(project)
    src = project / "downloaded.png"
    src.write_bytes(b"fake png data")
    r = CliRunner().invoke(main, ["file", str(src), "bird_crane"], catch_exceptions=False)
    assert r.exit_code == 0, r.output
    assert (project / "art/birds/crane@1x.png").read_bytes() == b"fake png data"


@case("file: derived resolutions still scale correctly")
def t_derived_scale(project):
    os.chdir(project)
    data = copy.deepcopy(SAMPLE_MANIFEST_DATA)
    data["assets"]["bird_crane"]["derived_resolutions"] = {
        "2x": {"destination": "art/birds/crane@2x.png", "dimensions": [96, 96], "filed_path": None},
        "3x": {"destination": "art/birds/crane@3x.png", "dimensions": [144, 144], "filed_path": None},
    }
    (project / "pipeline.json").write_text(json.dumps(data, indent=2))
    src = project / "big.png"
    Image.new("RGB", (512, 512), (128, 128, 128)).save(src)
    r = CliRunner().invoke(main, ["file", str(src), "bird_crane"], catch_exceptions=False)
    assert r.exit_code == 0, r.output
    with Image.open(project / "art/birds/crane@2x.png") as i:
        assert list(i.size) == [96, 96]
    with Image.open(project / "art/birds/crane@3x.png") as i:
        assert list(i.size) == [144, 144]


def main_run():
    for fn in (
        t_parse_creates, t_parse_reads_transparent,
        t_resize_oversized, t_preserve_alpha,
        t_strips_white, t_no_flag_leaves_bg,
        t_fallback_fake_bytes, t_derived_scale,
    ):
        fn()
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    for name, ok, tb in RESULTS:
        status = "PASS" if ok else "FAIL"
        print("[" + status + "] " + name)
        if not ok:
            print(tb)
    print("\n" + str(passed) + "/" + str(total) + " passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main_run()
