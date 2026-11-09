"""2.1 B4: `script` recipes — a committed program writes the asset, with only its declared inputs."""
from __future__ import annotations

import json

import pytest
from PIL import Image

from artpipeline import errors as E
from artpipeline.build import BuildError, compile_recipe, describe_change
from artpipeline.pipeline import Pipeline
from artpipeline.schema import BriefManifest
from test_build import TOKENS, write

SVG_SCRIPT = '''\
import json, sys
from artpipeline.build.script import job
j = job()
w = j["params"]["w"]
part = open("art/parts/dot.svg").read().strip()
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {j["master"][0]} {j["master"][1]}">'
       f'<rect y="27" width="{w}" height="10" fill="{j["tokens"]["gold"]}"/>{part}</svg>')
open(j["output"], "w").write(svg)
'''

PNG_SCRIPT = '''\
import json, sys
from PIL import Image
from pathlib import Path
from artpipeline.imaging.render import load_rgba
j = json.load(open(sys.argv[1]))
img = Image.new("RGBA", tuple(j["master"]), (0, 0, 0, 0))
for aid, p in sorted(j["assets"].items()):
    img.alpha_composite(load_rgba(Path(p), tuple(j["master"])).resize(tuple(j["master"])))
img.save(j["output"])
'''


def script_build(root, build, master=(64, 64), vector=True, assets=None, run=True, tokens=TOKENS):
    b = {"kind": "script", **build}
    return compile_recipe(root, b, tokens=tokens, asset={"id": "a"}, master=master, vector=vector,
                          assets=assets, run=run)


@pytest.fixture
def svg_recipe(tmp_path):
    write(tmp_path, "art/s.py", SVG_SCRIPT)
    write(tmp_path, "art/parts/dot.svg", '<circle cx="5" cy="5" r="2"/>')
    return {"script": "art/s.py", "inputs": ["art/parts/*.svg"], "params": {"w": 20}, "tokens": ["gold"]}


# ---------------------------------------------------------------- compiler

def test_script_runs_with_declared_inputs_and_records_them(tmp_path, svg_recipe):
    c = script_build(tmp_path, svg_recipe)
    assert c.kind == "script" and c.ext == ".svg" and b'fill="#F2C14E"' in c.svg and b"<circle" in c.svg
    rec = c.record()
    assert set(rec["inputs"]) == {"art/s.py", "art/parts/dot.svg"}
    assert rec["tokens"] == {"gold": "#F2C14E"} and rec["params"] == {"w": "20"} and rec["output"]
    # the fingerprint is known without running, and running doesn't change it
    assert script_build(tmp_path, svg_recipe, run=False).fingerprint == c.fingerprint
    # an undeclared token doesn't make it stale; a declared one does
    assert script_build(tmp_path, svg_recipe, tokens={**TOKENS, "ink": "#000000"}).fingerprint == c.fingerprint
    d = script_build(tmp_path, svg_recipe, tokens={**TOKENS, "gold": "#F5C451"})
    assert describe_change(rec, d.record()) == "tokens gold #F2C14E→#F5C451"
    write(tmp_path, "art/parts/dot.svg", '<circle cx="5" cy="5" r="3"/>')
    e = script_build(tmp_path, svg_recipe)
    assert describe_change(rec, e.record()) == "edited art/parts/dot.svg"


def test_undeclared_files_are_not_there(tmp_path, svg_recipe):
    with pytest.raises(BuildError, match=r"(?s)exited with 1:.*dot\.svg.*list every file"):
        script_build(tmp_path, {**svg_recipe, "inputs": []})
    with pytest.raises(BuildError, match="matches no files"):
        script_build(tmp_path, {**svg_recipe, "inputs": ["art/nope/*.svg"]})


def test_script_failures_are_build_errors(tmp_path):
    write(tmp_path, "art/none.py", "pass\n")
    with pytest.raises(BuildError, match="without writing the output"):
        script_build(tmp_path, {"script": "art/none.py"})
    write(tmp_path, "art/bad.py", "from artpipeline.build.script import job\nopen(job()['output'], 'w').write('<g/>')\n")
    with pytest.raises(BuildError, match="not <svg>"):
        script_build(tmp_path, {"script": "art/bad.py"})
    write(tmp_path, "art/junk.py", "from artpipeline.build.script import job\nopen(job()['output'], 'w').write('x')\n")
    with pytest.raises(BuildError, match="isn't a readable image"):
        script_build(tmp_path, {"script": "art/junk.py"}, vector=False)
    write(tmp_path, "art/slow.py", "import time\ntime.sleep(5)\n")
    with pytest.raises(BuildError, match="1s timeout"):
        script_build(tmp_path, {"script": "art/slow.py", "timeout": 1})
    with pytest.raises(BuildError, match="unknown token"):
        script_build(tmp_path, {"script": "art/none.py", "tokens": ["nope"]})
    with pytest.raises(BuildError, match="not found"):
        script_build(tmp_path, {"script": "art/missing.py"})


def test_environment_is_fixed(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "leak")
    write(tmp_path, "art/env.py", "import os\nfrom artpipeline.build.script import job\n"
                                  "open(job()['output'], 'w').write('<svg xmlns=\"http://www.w3.org/2000/svg\">'"
                                  " + '<!--' + os.environ.get('SECRET_TOKEN', 'none') + os.environ['TZ'] + '-->'"
                                  " + '</svg>')\n")
    assert b"<!--noneUTC-->" in script_build(tmp_path, {"script": "art/env.py"}).svg


# ---------------------------------------------------------------- schema

def _brief() -> dict:
    return {
        "version": 2, "project": "Demo", "direction": "Flat",
        "style": {"block": "Flat.", "tokens": dict(TOKENS)},
        "classes": {"ico": {"format": "svg", "master": [64, 64], "alpha": "required", "display_sizes": [64],
                            "checks": {"palette_min_share": None}},
                    "pic": {"format": "png", "master": [64, 64], "alpha": "required", "display_sizes": [64],
                            "checks": {"palette_min_share": None}}},
        "groups": {"bars": {"build": {"kind": "script", "script": "art/s.py", "inputs": ["art/parts/*.svg"],
                                      "tokens": ["gold"]}}},
        "assets": [
            {"id": "bar-wide", "class": "ico", "subject": "Bar", "acceptance_criteria": ["ok"],
             "destination": "ui/bar-wide.svg", "group": "bars", "hero": True, "build": {"params": {"w": 40}}},
            {"id": "bar-thin", "class": "ico", "subject": "Bar", "acceptance_criteria": ["ok"],
             "destination": "ui/bar-thin.svg", "group": "bars", "build": {"params": {"w": 10}}},
            {"id": "poster", "class": "pic", "subject": "Both bars", "acceptance_criteria": ["ok"],
             "destination": "ui/poster.png",
             "build": {"kind": "script", "script": "art/poster.py", "assets": ["bar-wide", "bar-thin"]}},
        ],
    }


def test_schema_script_rules():
    m = BriefManifest.model_validate(_brief())
    assert m.assets[1].build.script == "art/s.py" and m.assets[1].build.params == {"w": 10}

    def bad(mut, match):
        b = _brief()
        mut(b)
        with pytest.raises(ValueError, match=match):
            BriefManifest.model_validate(b)

    bad(lambda b: b["assets"][2]["build"].pop("script"), "needs script")
    bad(lambda b: b["assets"][2]["build"].update(layers=[{"fill": "#FFFFFF"}]), "takes no source")
    bad(lambda b: b["assets"][0].update(build={"kind": "svg", "source": "a.svg", "timeout": 5}),
        "belong to kind 'script'")
    bad(lambda b: b["assets"][2]["build"].update(inputs=["../x.py"]), "without '..'")
    bad(lambda b: b["assets"][2]["build"].update(assets=["ghost"]), "not in the brief")
    bad(lambda b: b["assets"][2]["build"].update(assets=["poster"]), "contains itself")


# ---------------------------------------------------------------- pipeline

@pytest.fixture
def sp(project, make_pipeline) -> Pipeline:
    write(project, "art/s.py", SVG_SCRIPT)
    write(project, "art/parts/dot.svg", '<circle cx="5" cy="5" r="2"/>')
    write(project, "art/poster.py", PNG_SCRIPT)
    p = make_pipeline(_brief())
    r = p.build("main", ["bar-wide"])["results"][0]
    assert r.get("status") == "awaiting_review", r
    p.review_sheet(["bar-wide"])
    p.decide("bar-wide", "approve", "user")
    p.lock_style("user")
    return p


def _approve(p: Pipeline, aid: str) -> dict:
    r = p.build("main", [aid])["results"][0]
    assert r.get("status") == "awaiting_review", r
    p.review_sheet([aid])
    p.decide(aid, "approve", "agent")
    return r


def test_script_assets_build_go_stale_and_depend(sp, project):
    att = sp.status("bar-wide")["attempts"][-1]
    assert att["build"]["kind"] == "script" and att["source"].endswith("source.svg")

    blocked = sp.build("main", ["poster"])["results"][0]
    assert blocked["error"] == E.BUILD_FAILED and "bar-thin" in blocked["message"]
    _approve(sp, "bar-thin")
    _approve(sp, "poster")
    with Image.open(project / "ui" / "poster.png") as im:
        assert im.size == (64, 64) and im.getpixel((2, 30))[3] == 255 and im.getpixel((50, 30))[3] == 0

    # Editing a declared input makes the script assets stale, and so (after re-approval) the poster.
    write(project, "art/parts/dot.svg", '<circle cx="5" cy="5" r="3"/>')
    stale = sp.status()["recipes"]["stale"]
    assert set(stale) == {"bar-wide", "bar-thin"}
    out = sp.build("main", stale=True)
    assert {r["asset_id"]: r["change"] for r in out["results"]}["bar-thin"] == \
        "rebuilt: edited art/parts/dot.svg"


def test_same_output_refreshes_the_record_without_reopening(sp, project):
    write(project, "art/s.py", SVG_SCRIPT + "# a comment\n")
    assert "bar-wide" in sp.status()["recipes"]["stale"]
    r = sp.build("main", ["bar-wide"])["results"][0]
    assert r["status"] == "up_to_date" and "writes the same file" in r["message"]
    st = sp.status("bar-wide")
    assert st["status"] == "approved" and len(st["attempts"]) == 1 and not st["stale"]
    doc = json.loads((project / "art-manifest.json").read_text())
    entry = next(a for a in doc["assets"] if a["id"] == "bar-wide")["approved"]["build"]
    assert entry["fingerprint"] == st["attempts"][-1]["build"]["fingerprint"]


def test_dry_run_flags_nondeterministic_scripts(sp, project):
    write(project, "art/s.py", "import random\nfrom artpipeline.build.script import job\nj = job()\n"
                               "open(j['output'], 'w').write('<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 64 64\">'"
                               " + f'<rect y=\"27\" width=\"{random.randint(1, 10**9) % 60 + 1}\" height=\"10\" fill=\"#F2C14E\"/></svg>')\n")
    r = sp.build("main", ["bar-thin"], dry_run=True)["results"][0]
    assert any("aren't reproducible" in w for w in r["warn"])
