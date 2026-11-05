"""The MCP server, exercised in-process through the official client."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import Client

from artpipeline import mcp_server
from conftest import make_manifest, make_png, write_brief

PROV = {"route": "code_native", "tool": "Claude SVG"}


@pytest.fixture(autouse=True)
def fresh_server(monkeypatch):
    monkeypatch.setattr(mcp_server, "_root", None)
    monkeypatch.delenv("ARTPIPELINE_ROOT", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)


def call(*steps):
    """Run (tool, args) steps in one client session; return the results."""
    async def go():
        out = []
        async with Client(mcp_server.server) as c:
            for name, args in steps:
                out.append(await c.call_tool(name, args))
        return out
    return asyncio.run(go())


def kinds(result):
    return [b.type for b in result.content]


def test_tools_are_listed_with_annotations():
    async def go():
        async with Client(mcp_server.server) as c:
            return await c.list_tools()
    tools = {t.name: t for t in asyncio.run(go()).tools}
    assert {"init", "claim", "register_attempt", "review_sheet", "decide", "lock_style", "pass_gate",
            "handback", "check_image", "contact_sheet"} <= set(tools)
    assert tools["status"].annotations.read_only_hint is True
    assert "user" in json.dumps(tools["lock_style"].input_schema["properties"]["by"])


def test_full_loop_over_mcp(tmp_path):
    brief = write_brief(tmp_path / "brief.md", make_manifest(n_assets=3, heroes=1))
    png = make_png(tmp_path / "gen" / "a.png")
    r = call(
        ("init", {"brief_path": str(brief)}),
        ("claim", {"agent": "main", "n": 3}),
        ("register_attempt", {"asset_id": "badge_00", "file": str(png), "agent": "main", **PROV}),
        ("decide", {"asset_id": "badge_00", "decision": "approve", "by": "user"}),
        ("lock_style", {"by": "user"}),
        ("claim", {"agent": "sub-1"}),
    )
    init, claim1, reg, dec, lock, claim2 = r
    assert init.structured_content["heroes"] == ["badge_00"]
    assert [a["asset_id"] for a in claim1.structured_content["claimed"]] == ["badge_00"]
    # the preview strip comes back inline and counts as review, so decide works straight away
    assert reg.structured_content["status"] == "awaiting_review"
    assert "image" in kinds(reg)
    assert dec.structured_content["status"] == "approved"
    assert lock.structured_content["version"] == 1
    # the locked hero is shown as a reference image to the next worker
    assert claim2.structured_content["claimed"][0]["style"]["lock_version"] == 1
    assert "image" in kinds(claim2)


def test_errors_are_tool_errors_with_codes(tmp_path):
    brief = write_brief(tmp_path / "brief.md", make_manifest())
    init, lock, decide = call(
        ("init", {"brief_path": str(brief)}),
        ("lock_style", {"by": "user"}),
        ("decide", {"asset_id": "nope", "decision": "approve", "by": "agent"}),
    )
    assert lock.is_error and lock.structured_content["error"] == "HEROES_NOT_APPROVED"
    assert decide.is_error and decide.structured_content["error"] == "ASSET_NOT_FOUND"


def test_agent_cannot_claim_user_signoff(tmp_path):
    brief = write_brief(tmp_path / "brief.md", make_manifest())
    _, lock = call(("init", {"brief_path": str(brief)}), ("lock_style", {"by": "agent"}))
    assert lock.is_error  # rejected by the schema: by must be "user"


def test_discovery_from_project_dir(tmp_path, monkeypatch):
    art = tmp_path / "art"
    art.mkdir()
    brief = write_brief(art / "brief.md", make_manifest())
    call(("init", {"brief_path": str(brief)}))
    mcp_server._root = None
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))  # pipeline lives one level down
    (st,) = call(("status", {}))
    assert st.structured_content["counts"] == {"pending": 4}


def test_review_sheet_and_handback_return_images(tmp_path):
    m = make_manifest(n_assets=2, heroes=0)
    brief = write_brief(tmp_path / "brief.md", m)
    png = make_png(tmp_path / "gen" / "a.png")
    steps = [("init", {"brief_path": str(brief)}), ("claim", {"agent": "main", "n": 2})]
    for aid in ("badge_00", "badge_01"):
        steps.append(("register_attempt", {"asset_id": aid, "file": str(png), "agent": "main",
                                           "preview": False, **PROV}))
    steps += [("review_sheet", {"pending_review": True}),
              ("decide", {"asset_id": "badge_00", "decision": "approve", "by": "agent"}),
              ("decide", {"asset_id": "badge_01", "decision": "reject", "by": "agent", "reason": "too dark"}),
              ("handback", {})]
    res = call(*steps)
    sheet, handback = res[4], res[-1]
    assert kinds(sheet).count("image") == 2  # one strip per asset
    hb = handback.structured_content
    assert hb["counts"] == {"pending": 1, "approved": 1}
    assert hb["unfinished"] == [{"asset_id": "badge_01", "status": "pending"}]
    assert "image" in kinds(handback) and Path(hb["final_sheet"][0]).is_file()
    assert sheet.structured_content["shown"] == [{"sizes_px": [64, 32], "backgrounds": ["#23282B", "#49606B"],
                                                  "greyscale": True, "icon_mask": False, "assets": 2}]
    assert hb["assets"][0] == {"asset_id": "badge_00", "status": "approved", "attempts": 1,
                               "file": "badges/badge_00.png", "tool": "Claude SVG", "route": "code_native"}


def test_stateless_tools(tmp_path):
    png = make_png(tmp_path / "a.png", size=(256, 256))
    chk, sheet = call(
        ("check_image", {"files": [str(png)], "preset": "game_center_badge"}),
        ("contact_sheet", {"files": [str(png)], "out_path": str(tmp_path / "s.png"), "sizes": [128, 32]}),
    )
    assert chk.structured_content["pass"] is False
    assert "size 256x256 != 1024x1024" in chk.structured_content["results"][0]["fail"]
    assert "image" in kinds(sheet)


def test_stdio_server_starts(tmp_path):
    """The console script speaks MCP over stdio (what the plugin launches)."""
    from mcp import StdioServerParameters

    params = StdioServerParameters(command=sys.executable, args=["-m", "artpipeline.cli", "mcp"],
                                   env={**os.environ, "ARTPIPELINE_ROOT": str(tmp_path)})

    async def go():
        async with Client(params) as c:
            return [t.name for t in (await c.list_tools()).tools]
    assert "claim" in asyncio.run(go())


def test_provisional_lock_over_mcp(tmp_path):
    brief = write_brief(tmp_path / "brief.md", make_manifest(n_assets=2, heroes=1))
    png = make_png(tmp_path / "gen" / "a.png")
    *_, lock, claim, hb = call(
        ("init", {"brief_path": str(brief)}),
        ("claim", {"agent": "main"}),
        ("register_attempt", {"asset_id": "badge_00", "file": str(png), "agent": "main", **PROV}),
        ("decide", {"asset_id": "badge_00", "decision": "approve", "by": "agent"}),
        ("lock_style", {"by": "agent", "provisional": True}),
        ("claim", {"agent": "main"}),
        ("handback", {}),
    )
    assert lock.structured_content["provisional"] is True
    assert claim.structured_content["claimed"][0]["style"]["provisional"] is True
    assert "provisional" in hb.structured_content["waiting_for_user"]
    assert (tmp_path / "badges" / "badge_00.png").is_file()  # staged on approval


def test_batch_register_decide_and_grid(tmp_path):
    m = make_manifest(n_assets=9, heroes=0)
    m["assets"][0]["notes"] = "in-game title: First Shift"  # notes are allowed on assets
    brief = write_brief(tmp_path / "brief.md", m)
    good = make_png(tmp_path / "gen" / "a.png")
    bad = make_png(tmp_path / "gen" / "b.png", size=(32, 32))
    ids = [f"badge_{i:02d}" for i in range(8)]
    init, claim, pre, reg, dec = call(
        ("init", {"brief_path": str(brief)}),
        ("claim", {"agent": "main", "n": 8}),
        ("check_image", {"files": [str(bad)], "asset_id": "badge_07"}),
        ("register_attempts", {"agent": "main", "route": "code_native", "tool": "Claude SVG",
                               "attempts": [{"asset_id": a, "file": str(good if a != "badge_07" else bad)}
                                            for a in ids]}),
        ("decide_batch", {"by": "agent", "decisions": [
            {"asset_id": "badge_00", "decision": "approve"},
            {"asset_id": "badge_01", "decision": "reject"},            # no reason: refused, others proceed
            {"asset_id": "badge_02", "decision": "reject", "reason": "too dark"},
            {"asset_id": "badge_07", "decision": "approve"}]}),        # failed checks: not reviewable
    )
    assert not init.is_error
    assert pre.structured_content["pass"] is False  # free pre-check against the asset's own class
    assert claim.structured_content["claimed"][7]["attempts_used"] == 0
    r = reg.structured_content
    assert r["counts"] == {"awaiting_review": 7, "in_progress": 1}
    assert kinds(reg).count("image") == 1  # one grid page, not 7 strips
    d = dec.structured_content
    assert d["counts"] == {"approved": 1, "error": 2, "pending": 1}
    errs = {x["asset_id"]: x["error"] for x in d["results"] if "error" in x}
    assert errs == {"badge_01": "REASON_REQUIRED", "badge_07": "INVALID_STATE"}


def test_place_over_mcp(tmp_path):
    brief = write_brief(tmp_path / "brief.md", make_manifest(n_assets=1, heroes=1))
    png = make_png(tmp_path / "gen" / "a.png")
    godot = tmp_path / "game"
    godot.mkdir()
    (godot / "project.godot").write_text("")
    *_, placed = call(
        ("init", {"brief_path": str(brief)}),
        ("claim", {"agent": "main"}),
        ("register_attempt", {"asset_id": "badge_00", "file": str(png), "agent": "main", **PROV}),
        ("decide", {"asset_id": "badge_00", "decision": "approve", "by": "user"}),
        ("lock_style", {"by": "user"}),
        ("place", {"target": "godot", "project_dir": str(godot)}),
    )
    out = placed.structured_content
    assert out["placed"] == 1 and out["res_paths"]["badge_00"] == "res://badges/badge_00.png"
    assert (godot / "badges" / "badge_00.png.import").is_file()
    m = json.loads((tmp_path / "art-manifest.json").read_text())
    assert "godot" in m["assets"][0]["approved"]["placed"]
