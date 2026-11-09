"""2.1 B1: building assets from svg recipes — compiler, schema, pipeline build/stale, MCP and CLI."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
from PIL import Image

from artpipeline import errors as E
from artpipeline.build import BuildError, compile_recipe, describe_change
from artpipeline.errors import PipelineError
from artpipeline.pipeline import Pipeline
from artpipeline.schema import BriefManifest
from artpipeline.store import Store
from conftest import make_manifest, write_brief

TOKENS = {"teal": "#22B8B0", "gold": "#F2C14E", "ink": "#23282B"}

FRAME = """<?xml version="1.0"?>
<svg viewBox="0 0 64 64" width="64" height="64">
  <rect width="64" height="64" fill="{{tokens.ink}}"/>
  <rect x="6" y="6" width="52" height="52" fill="{{band}}"/>
  <ap:slot/>
</svg>
"""


def glyph(color: str = "tokens.gold") -> str:
    return f'<rect x="20" y="20" width="24" height="24" fill="{{{{{color}}}}}"/>\n'


def compile_(root: Path, build: dict, tokens=TOKENS, master=(64, 64), asset=None):
    return compile_recipe(root, build, tokens=tokens, asset=asset or {"id": "a"}, master=master)


def write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# ---------------------------------------------------------------- compiler

def test_substitution_tokens_params_and_asset(tmp_path):
    write(tmp_path, "a.svg", '<rect fill="{{tokens.gold}}" stroke="{{band}}" id="{{asset.id}}" '
                             'data-t="{{params.title}}"/>')
    c = compile_(tmp_path, {"source": "a.svg", "params": {"band": "$teal", "title": "A & B"}},
                 asset={"id": "first-shift"})
    svg = c.svg.decode()
    assert 'fill="#F2C14E"' in svg and 'stroke="#22B8B0"' in svg and 'id="first-shift"' in svg
    assert "A &amp; B" in svg
    assert c.tokens == {"gold": "#F2C14E", "teal": "#22B8B0"}  # used directly or through a $param
    assert c.params == {"band": "$teal", "title": "A & B"}  # as written; token values are in c.tokens
    assert 'viewBox="0 0 64 64"' in svg  # a fragment is wrapped at the class master


def test_unknown_names_and_expressions_are_errors(tmp_path):
    write(tmp_path, "a.svg", '<rect fill="{{tokens.purple}}"/>')
    with pytest.raises(BuildError, match="unknown name 'tokens.purple'"):
        compile_(tmp_path, {"source": "a.svg"})
    write(tmp_path, "b.svg", '<rect width="{{ 2 * 3 }}"/>')
    with pytest.raises(BuildError, match="not a name"):
        compile_(tmp_path, {"source": "b.svg"})
    with pytest.raises(BuildError, match="token 'nope'"):
        compile_(tmp_path, {"source": "a.svg", "params": {"x": "$nope"}})


def test_template_slots_parts_and_defaults(tmp_path):
    write(tmp_path, "t.svg", '<svg viewBox="0 0 10 10"><ap:slot/><ap:slot name="title"><g id="dflt"/></ap:slot>'
                             '<ap:slot name="extra"><g id="keep"/></ap:slot></svg>')
    write(tmp_path, "s.svg", '<svg viewBox="0 0 10 10"><circle id="body" r="1"/>'
                             '<ap:part name="title"><g id="t"/></ap:part></svg>')
    svg = compile_(tmp_path, {"source": "s.svg", "template": "t.svg"}).svg.decode()
    assert 'id="body"' in svg and 'id="t"' in svg and 'id="keep"' in svg and 'id="dflt"' not in svg
    write(tmp_path, "bad.svg", '<ap:part name="nowhere"><g/></ap:part>')
    with pytest.raises(BuildError, match="nowhere"):
        compile_(tmp_path, {"source": "bad.svg", "template": "t.svg"})


def test_includes_cycles_and_missing_files(tmp_path):
    write(tmp_path, "parts/rivet.svg", '<circle id="rivet" fill="{{ink}}" r="2"/>')
    write(tmp_path, "a.svg", '<g><ap:include src="parts/rivet.svg"/></g>')
    c = compile_(tmp_path, {"source": "a.svg"})
    assert 'id="rivet"' in c.svg.decode() and 'fill="#23282B"' in c.svg.decode()
    assert set(c.inputs) == {"a.svg", "parts/rivet.svg"}
    write(tmp_path, "x.svg", '<ap:include src="y.svg"/>')
    write(tmp_path, "y.svg", '<ap:include src="x.svg"/>')
    with pytest.raises(BuildError, match="cycle"):
        compile_(tmp_path, {"source": "x.svg"})
    with pytest.raises(BuildError, match="not found: missing.svg"):
        compile_(tmp_path, {"source": "missing.svg"})


def test_local_images_are_embedded_and_remote_refused(tmp_path):
    Image.new("RGB", (4, 4), (255, 0, 0)).save(tmp_path / "tex.png")
    write(tmp_path, "a.svg", '<image href="tex.png" width="4" height="4"/>')
    c = compile_(tmp_path, {"source": "a.svg"})
    assert "data:image/png;base64," in c.svg.decode() and "tex.png" in c.inputs
    write(tmp_path, "r.svg", '<image href="https://example.com/x.png"/>')
    with pytest.raises(BuildError, match="remote"):
        compile_(tmp_path, {"source": "r.svg"})


def test_shapes_expand_to_plain_svg(tmp_path):
    write(tmp_path, "a.svg", '<ap:star cx="32" cy="32" r="20" points="5" fill="red" id="s"/>'
                             '<ap:polygon cx="32" cy="32" r="10" sides="6"/>'
                             '<ap:ring cx="32" cy="32" r="30" width="4"/>'
                             '<ap:arc cx="32" cy="32" r="20" start="0" end="90" sector="true"/>'
                             '<ap:gear cx="32" cy="32" r="16" teeth="8" hole="0.3"/>'
                             '<ap:burst cx="32" cy="32" r="30" rays="12"/>')
    svg = compile_(tmp_path, {"source": "a.svg"}).svg.decode()
    assert "ap:" not in svg and AP_NS_ABSENT(svg)
    star = svg.split('id="s"')[0].rsplit("<polygon", 1)[1] + svg.split('id="s"')[1].split("/>")[0]
    assert len(star.split('points="')[1].split('"')[0].split()) == 10
    assert 'fill="red"' in svg and svg.count('fill-rule="evenodd"') == 2
    write(tmp_path, "b.svg", '<ap:arc cx="0" cy="0" r="5" start="90" end="10"/>')
    with pytest.raises(BuildError, match="end must be greater"):
        compile_(tmp_path, {"source": "b.svg"})
    write(tmp_path, "c.svg", '<ap:hexagon/>')
    with pytest.raises(BuildError, match="unknown element <ap:hexagon>"):
        compile_(tmp_path, {"source": "c.svg"})
    write(tmp_path, "d.svg", '<ap:star cx="0" cy="0"/>')
    with pytest.raises(BuildError, match="needs a 'r'"):
        compile_(tmp_path, {"source": "d.svg"})


def AP_NS_ABSENT(svg: str) -> bool:
    return "artpipelinetool/ns/build" not in svg


def test_builds_are_deterministic_and_track_inputs(tmp_path):
    write(tmp_path, "t.svg", FRAME)
    write(tmp_path, "a.svg", glyph())
    b = {"source": "a.svg", "template": "t.svg", "params": {"band": "$teal"}}
    c1, c2 = compile_(tmp_path, b), compile_(tmp_path, b)
    assert c1.svg == c2.svg and c1.fingerprint == c2.fingerprint
    c3 = compile_(tmp_path, b, tokens={**TOKENS, "gold": "#FFD000"})
    assert c3.fingerprint != c1.fingerprint
    assert describe_change(c1.record(), c3.record()) == "tokens gold #F2C14E→#FFD000"
    unused = compile_(tmp_path, b, tokens={**TOKENS, "spare": "#000000"})
    assert unused.fingerprint == c1.fingerprint  # unused tokens don't make an asset stale
    write(tmp_path, "t.svg", FRAME.replace('x="6"', 'x="5"'))
    assert describe_change(c1.record(), compile_(tmp_path, b).record()) == "edited t.svg"


def test_rendered_build_matches_tokens(tmp_path):
    from artpipeline.imaging.render import render_svg

    write(tmp_path, "t.svg", FRAME)
    write(tmp_path, "a.svg", glyph())
    c = compile_(tmp_path, {"source": "a.svg", "template": "t.svg", "params": {"band": "$teal"}})
    f = tmp_path / "out.svg"
    f.write_bytes(c.svg)
    img = render_svg(f, 64).convert("RGB")
    assert img.getpixel((1, 1)) == (0x23, 0x28, 0x2B)
    assert img.getpixel((10, 10)) == (0x22, 0xB8, 0xB0)
    assert img.getpixel((32, 32)) == (0xF2, 0xC1, 0x4E)


# ---------------------------------------------------------------- schema

def _brief(**over) -> dict:
    m = make_manifest(n_assets=4, heroes=1)
    m["style"] = {"block": "Flat.", "tokens": dict(TOKENS), "backgrounds": ["#23282B"]}
    m["groups"] = {"even": {"build": {"template": "art/frame.svg", "params": {"band": "$teal"}}},
                   "odd": {"build": {"template": "art/frame.svg", "params": {"band": "$teal"}}}}
    for a in m["assets"]:
        a["build"] = {"source": f"art/{a['id']}.svg"}
    m.update(over)
    return m


def test_schema_tokens_groups_and_recipe_paths():
    m = BriefManifest.model_validate(_brief())
    assert m.style.palette == list(TOKENS.values())
    assert m.assets[0].build.template == "art/frame.svg" and m.assets[0].build.params == {"band": "$teal"}
    with pytest.raises(ValueError, match="in the palette"):
        BriefManifest.model_validate(_brief(style={"tokens": {"x": "#000000"}, "palette": ["#FFFFFF"]}))
    bad = _brief()
    bad["assets"][0]["build"] = {"source": "/abs/a.svg"}
    with pytest.raises(ValueError, match="relative"):
        BriefManifest.model_validate(bad)
    empty = _brief(groups={})
    empty["assets"][0]["build"] = {"params": {"a": 1}}
    with pytest.raises(ValueError, match="needs a source, a template"):
        BriefManifest.model_validate(empty)


# ---------------------------------------------------------------- pipeline

@pytest.fixture
def recipes(project: Path) -> Path:
    write(project, "art/frame.svg", FRAME)
    for i, color in enumerate(["tokens.gold", "tokens.teal", "tokens.gold", "tokens.teal"]):
        write(project, f"art/badge_{i:02d}.svg", glyph(color) if i != 1 else glyph("tokens.gold"))
    return project


@pytest.fixture
def bp(recipes, make_pipeline) -> Pipeline:
    return make_pipeline(_brief())


def test_build_hero_registers_attempt_with_recipe(bp, project):
    out = bp.build("main", ["badge_00"])
    r = out["results"][0]
    assert r["status"] == "awaiting_review", r
    assert out["passing"] == ["badge_00"]
    att = bp.status("badge_00")["attempts"][0]
    assert att["provenance"]["tool"] == "artpipeline build (svg)"
    assert att["provenance"]["route"] == "code_native"
    assert set(att["build"]["inputs"]) == {"art/badge_00.svg", "art/frame.svg"}
    assert att["source"].endswith("source.svg")
    bp.review_sheet(["badge_00"])
    bp.decide("badge_00", "approve", "user")
    doc = json.loads((project / "art-manifest.json").read_text())
    entry = doc["assets"][0]["approved"]
    assert entry["build"]["inputs"] == ["art/badge_00.svg", "art/frame.svg"]
    assert entry["build"]["tokens"] == {"gold": "#F2C14E", "ink": "#23282B", "teal": "#22B8B0"}
    assert doc["tokens"] == TOKENS
    assert (project / "badges" / "badge_00.png").is_file()  # staged like any approved attempt


def test_group_build_respects_the_style_lock(bp):
    out = bp.build("main", group="even")
    assert [r["asset_id"] for r in out["results"]] == ["badge_00"]
    assert "wait for the style lock" in out["note"]
    out = bp.build("main", ["badge_02"])
    assert out["results"][0]["error"] == E.STYLE_NOT_LOCKED


def test_packets_carry_the_recipe_and_tokens(bp):
    pkt = bp.claim("main", asset_ids=["badge_00"])["claimed"][0]
    assert pkt["build"]["template"] == "art/frame.svg"
    assert pkt["style"]["tokens"] == TOKENS
    assert "build(asset_ids=['badge_00'])" in pkt["next"]


def test_rebuild_after_rejection_needs_a_cause_and_a_change(bp, project):
    bp.build("main", ["badge_00"])
    bp.review_sheet(["badge_00"])
    bp.decide("badge_00", "reject", "agent", "glyph too small at 32 px")
    same = bp.build("main", ["badge_00"], change_from_previous="bigger glyph")["results"][0]
    assert same["error"] == E.NO_CAUSE_CHANGE and "same file" in same["message"]
    write(project, "art/badge_00.svg", '<rect x="12" y="12" width="40" height="40" fill="{{tokens.gold}}"/>')
    silent = bp.build("main", ["badge_00"])["results"][0]
    assert silent["error"] == E.NO_CAUSE_CHANGE and "edited art/badge_00.svg" in silent["hint"]
    ok = bp.build("main", ["badge_00"], change_from_previous="glyph 24→40 px")["results"][0]
    assert ok["status"] == "awaiting_review" and ok["attempt"] == 2
    assert ok["change"] == "glyph 24→40 px (recipe: edited art/badge_00.svg)"


def test_broken_recipe_uses_no_attempt(bp, project):
    write(project, "art/badge_00.svg", "<rect fill='{{tokens.nope}}'/>")
    r = bp.build("main", ["badge_00"])["results"][0]
    assert r["error"] == E.BUILD_FAILED and "tokens.nope" in r["message"]
    assert bp.status("badge_00")["attempts"] == []
    assert bp.status("badge_00")["status"] == "pending"


def test_no_recipe(make_pipeline):
    p = make_pipeline()
    assert p.build("main", ["badge_00"])["results"][0]["error"] == E.NO_RECIPE


def _approve_heroes_and_lock(p: Pipeline) -> None:
    p.build("main", ["badge_00"])
    p.review_sheet(["badge_00"])
    p.decide("badge_00", "approve", "user")
    p.lock_style("user")


def test_stale_after_template_edit_rebuilds_without_spending_budget(bp, project):
    _approve_heroes_and_lock(bp)
    bp.build("main", group="odd")
    bp.review_sheet(pending_review=True)
    bp.decide_batch([{"asset_id": "badge_01", "decision": "approve"},
                     {"asset_id": "badge_03", "decision": "approve"}], "agent")
    assert bp.status()["recipes"]["stale"] == []
    assert bp.build("main", ["badge_01"])["results"][0]["status"] == "up_to_date"

    write(project, "art/frame.svg", FRAME.replace('x="6" y="6" width="52" height="52"',
                                                  'x="4" y="4" width="56" height="56"'))
    st = bp.status()
    assert st["recipes"]["stale"] == ["badge_00", "badge_01", "badge_03"]
    assert bp.status("badge_01")["stale"] is True

    out = bp.build("main", stale=True)
    by = {r["asset_id"]: r for r in out["results"]}
    assert by["badge_01"]["status"] == "awaiting_review"
    assert by["badge_01"]["reopened_from"] == "approved"
    assert by["badge_01"]["change"] == "rebuilt: edited art/frame.svg"
    one = bp.status("badge_01")
    assert one["attempts_left"] == 2  # the stale rebuild came with its own extra attempt
    assert [a["decision"] for a in one["attempts"]] == ["superseded", None]
    assert bp.status()["recipes"]["stale"] == []
    kinds = [e["kind"] for e in bp.history("badge_01")["events"]]
    assert "reopen" in kinds


def test_token_change_in_lock_marks_built_assets_stale(bp):
    _approve_heroes_and_lock(bp)
    bp.build("main", ["badge_01"])
    bp.review_sheet(["badge_01"])
    bp.decide("badge_01", "approve", "agent")
    new = {**TOKENS, "gold": "#F5C451"}
    lock = bp.lock_style("user", tokens=new)
    assert lock["tokens"] == new and lock["palette"] == list(new.values())
    assert sorted(lock["stale"]) == ["badge_00", "badge_01"]
    assert "build(stale=true)" in lock["next"]
    out = bp.build("main", stale=True)
    changes = {r["asset_id"]: r.get("change") for r in out["results"]}
    assert changes["badge_01"] == "rebuilt: tokens gold #F2C14E→#F5C451"


def test_lock_tokens_must_fit_the_palette(bp):
    bp.build("main", ["badge_00"])
    bp.review_sheet(["badge_00"])
    bp.decide("badge_00", "approve", "user")
    with pytest.raises(PipelineError) as e:
        bp.lock_style("user", palette=["#FFFFFF"])
    assert e.value.code == E.INVALID_ARGUMENT and "tokens" in e.value.hint


def test_dry_run_changes_nothing(bp):
    out = bp.build("main", ["badge_00"], dry_run=True)
    r = out["results"][0]
    assert r["pass"] is True and Path(r["strip"]).is_file() and Path(r["built"]).is_file()
    assert out["counts"] == {"pass": 1}
    assert bp.status("badge_00")["status"] == "pending"
    assert bp.status("badge_00")["attempts"] == []
    # non-heroes can be dry-run before the lock: it's free and stateless
    assert bp.build("main", group="odd", dry_run=True)["counts"] == {"pass": 2}


def test_build_needs_a_target(bp):
    with pytest.raises(PipelineError) as e:
        bp.build("main")
    assert e.value.code == E.INVALID_ARGUMENT


def test_v3_pipeline_migrates(bp, project):
    db = project / ".artpipeline" / "pipeline.db"
    con = sqlite3.connect(db)
    con.execute("ALTER TABLE attempts DROP COLUMN build")
    con.execute("ALTER TABLE style_locks DROP COLUMN tokens")
    con.execute("UPDATE meta SET value='3' WHERE key='schema_version'")
    con.commit()
    con.close()
    p = Pipeline(Store.open(project))
    assert p.build("main", ["badge_00"])["results"][0]["status"] == "awaiting_review"
    con = sqlite3.connect(db)
    assert con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "4"
    con.close()


# ---------------------------------------------------------------- MCP and CLI

def test_build_over_mcp(recipes, tmp_path, monkeypatch):
    from mcp import Client

    from artpipeline import mcp_server

    monkeypatch.setattr(mcp_server, "_root", None)
    monkeypatch.delenv("ARTPIPELINE_ROOT", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    brief = write_brief(recipes / "brief.md", _brief())

    async def go():
        async with Client(mcp_server.server) as c:
            await c.call_tool("init", {"brief_path": str(brief)})
            dry = await c.call_tool("build", {"agent": "main", "asset_ids": ["badge_00"], "dry_run": True})
            real = await c.call_tool("build", {"agent": "main", "asset_ids": ["badge_00"]})
            dec = await c.call_tool("decide", {"asset_id": "badge_00", "decision": "approve", "by": "user"})
            return dry, real, dec

    dry, real, dec = asyncio.run(go())
    assert "image" in [b.type for b in dry.content]
    assert real.structured_content["passing"] == ["badge_00"]
    assert "image" in [b.type for b in real.content]  # the inline view counts as review...
    assert dec.structured_content["status"] == "approved"  # ...so decide works straight away


def test_build_over_cli(recipes, monkeypatch, capsys):
    from artpipeline.cli import run

    brief = write_brief(recipes / "brief.md", _brief())
    monkeypatch.chdir(recipes)
    assert run(["init", str(brief)])[0] == 0
    code, out = run(["build", "badge_00", "--agent", "main"])
    assert code == 0 and out["results"][0]["status"] == "awaiting_review"
    code, out = run(["build", "--agent", "main", "--group", "odd", "--dry-run"])
    assert code == 0 and out["counts"] == {"pass": 2}


def _approve_all(p: Pipeline) -> None:
    _approve_heroes_and_lock(p)
    p.build("main", ["badge_01", "badge_02", "badge_03"])
    p.review_sheet(pending_review=True)
    p.decide_batch([{"asset_id": a, "decision": "approve"} for a in ("badge_01", "badge_02", "badge_03")], "agent")


def test_relock_keeps_what_the_new_tokens_dont_change(bp, project):
    write(project, "art/badge_03.svg", '<rect x="20" y="20" width="24" height="24" fill="{{tokens.ink}}"/>')
    write(project, "art/frame.svg", FRAME.replace("{{band}}", "{{tokens.ink}}"))
    _approve_all(bp)
    lock = bp.lock_style("user", tokens={**TOKENS, "gold": "#F5C451"})
    assert sorted(lock["rereview"]) == ["badge_01", "badge_02"]
    assert lock["unchanged"] == ["badge_03"]
    assert bp.status("badge_03")["status"] == "approved" and bp.status("badge_03")["stale"] is False


def test_relock_rereviews_everything_when_the_style_text_changes(bp, project):
    write(project, "art/badge_03.svg", '<rect x="20" y="20" width="24" height="24" fill="{{tokens.ink}}"/>')
    _approve_all(bp)
    lock = bp.lock_style("user", style_block="Flat, but different.", tokens={**TOKENS, "gold": "#F5C451"})
    assert "badge_03" in lock["rereview"] and "unchanged" not in lock


def test_relock_rereviews_a_hard_coded_colour_the_palette_dropped(bp, project):
    write(project, "art/badge_03.svg", '<rect x="20" y="20" width="24" height="24" fill="#F2C14E"/>')
    _approve_all(bp)
    lock = bp.lock_style("user", tokens={**TOKENS, "gold": "#F5C451"})
    assert "badge_03" in lock["rereview"]
    assert "badge_03" not in lock.get("unchanged", [])


def test_build_refuses_ids_with_a_selection(bp):
    for kw in ({"group": "odd"}, {"stale": True}):
        with pytest.raises(PipelineError) as e:
            bp.build("main", ["badge_00"], **kw)
        assert e.value.code == E.INVALID_ARGUMENT
