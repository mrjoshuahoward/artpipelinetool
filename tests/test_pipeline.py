from __future__ import annotations

import json

import pytest

from artpipeline import errors as E
from artpipeline.errors import PipelineError
from artpipeline.pipeline import Pipeline
from conftest import PROV, approve, make_manifest, make_png, write_brief


def code(exc_info) -> str:
    return exc_info.value.code


# ---------------------------------------------------------------- init / refresh

def test_init_creates_state_and_manifest(make_pipeline, project):
    p = make_pipeline()
    assert (project / ".artpipeline" / "pipeline.db").is_file()
    assert (project / ".artpipeline" / ".gitignore").read_text() == "*\n"
    doc = json.loads((project / "art-manifest.json").read_text())
    assert doc["counts"] == {"pending": 4}
    assert p.status()["counts"] == {"pending": 4}


def test_refresh_keeps_progress_and_reports_changes(make_pipeline, project, good_png, clock):
    p = make_pipeline()
    approve(p, "badge_00", good_png)
    m = make_manifest()
    m["assets"][0]["subject"] = "Changed subject"
    m["assets"].pop()  # badge_03 removed
    m["assets"].append({**m["assets"][1], "id": "badge_new", "destination": "badges/new.png"})
    _, report = Pipeline.init(write_brief(project / "brief.md", m), clock=clock)
    assert report["added"] == ["badge_new"]
    assert report["changed"] == [{"id": "badge_00", "status": "approved"}]
    assert report["removed"] == ["badge_03"]
    assert any("re-review" in w for w in report["warnings"])
    st = p.status()
    assert st["counts"] == {"approved": 1, "pending": 3}


def test_project_mismatch(make_pipeline, project, clock):
    make_pipeline()
    with pytest.raises(PipelineError) as e:
        Pipeline.init(write_brief(project / "brief.md", make_manifest(project="Other")), clock=clock)
    assert code(e) == E.PROJECT_MISMATCH


def test_no_heroes_warns(make_pipeline, project, clock):
    _, report = Pipeline.init(write_brief(project / "brief.md", make_manifest(heroes=0)), clock=clock)
    assert any("No hero assets" in w for w in report["warnings"])


# ---------------------------------------------------------------- style lock

def test_heroes_first_then_lock(make_pipeline, good_png):
    p = make_pipeline()
    out = p.claim("main", n=4)
    assert [a["asset_id"] for a in out["claimed"]] == ["badge_00", "badge_01"]
    assert "hero" in out["note"]
    with pytest.raises(PipelineError) as e:
        p.claim("main")
    assert code(e) == E.STYLE_NOT_LOCKED
    assert e.value.details["heroes"] == {"badge_00": "in_progress", "badge_01": "in_progress"}

    with pytest.raises(PipelineError) as e:
        p.lock_style("user")
    assert code(e) == E.HEROES_NOT_APPROVED

    for h in ("badge_00", "badge_01"):
        p.register_attempt(h, good_png, "main", PROV)
        p.record_sheet(good_png, [h])
        p.decide(h, "approve", "user")

    with pytest.raises(PipelineError) as e:
        p.lock_style("agent")
    assert code(e) == E.USER_SIGNOFF_REQUIRED

    lock = p.lock_style("user")
    assert lock["version"] == 1
    assert len(lock["references"]) == 2

    packet = p.claim("sub-1")["claimed"][0]
    assert packet["asset_id"] == "badge_02"
    assert packet["style"]["lock_version"] == 1
    assert packet["style"]["block"].startswith("Flat vector")
    assert packet["spec"]["master"] == [64, 64]


def test_relock_sends_approved_assets_back_to_review(make_pipeline, good_png):
    p = make_pipeline()
    approve(p, "badge_00", good_png, by="user")
    approve(p, "badge_01", good_png, by="user")
    p.lock_style("user")
    approve(p, "badge_02", good_png)
    out = p.lock_style("user", "New style block")
    assert out["version"] == 2 and out["rereview"] == ["badge_02"]
    assert p.status("badge_02")["status"] == "awaiting_review"
    with pytest.raises(PipelineError) as e:
        p.decide("badge_02", "approve", "agent")
    assert code(e) == E.NOT_REVIEWED


def test_provisional_lock_when_user_is_away(make_pipeline, good_png, project):
    m = make_manifest(n_assets=6, heroes=2)
    m["settings"]["gate_threshold"] = 3
    p = make_pipeline(m)
    approve(p, "badge_00", good_png)
    approve(p, "badge_01", good_png)
    with pytest.raises(PipelineError) as e:
        p.lock_style("agent")
    assert code(e) == E.USER_SIGNOFF_REQUIRED and "provisional" in e.value.hint
    with pytest.raises(PipelineError) as e:
        p.lock_style("user", provisional=True)
    assert code(e) == E.INVALID_ARGUMENT

    lock = p.lock_style("agent", provisional=True)
    assert lock["version"] == 1 and lock["provisional"] is True
    packet = p.claim("main")["claimed"][0]
    assert packet["style"]["provisional"] is True
    p.release(packet["asset_id"], "main")
    # gates are deferred under a provisional lock: 3 approvals reach the threshold of 3, no gate
    for aid in ("badge_02", "badge_03", "badge_04"):
        approve(p, aid, good_png)
    assert p.status()["open_gate"] is None and p.status()["style_lock_provisional"] is True

    doc = json.loads((project / "art-manifest.json").read_text())
    assert doc["style_lock"]["provisional"] is True
    assert all(a["approved"]["provisional"] for a in doc["assets"] if a["approved"] and not a["hero"])
    hb = p.handback()
    assert hb["style_lock_provisional"] is True and "provisional" in hb["waiting_for_user"]

    # the agent cannot override a user lock with a provisional one
    real = p.lock_style("user")
    assert real["version"] == 2 and real["provisional"] is False
    assert real["rereview"] == ["badge_02", "badge_03", "badge_04"]  # heroes stay approved
    with pytest.raises(PipelineError) as e:
        p.lock_style("agent", provisional=True)
    assert code(e) == E.INVALID_STATE
    assert "waiting_for_user" not in p.handback()


def test_approved_files_are_staged_without_clobbering(make_pipeline, good_png, project, clock):
    m = make_manifest(n_assets=2, heroes=0)
    m["classes"]["badge"]["renditions"] = [{"suffix": "-32", "size": [32, 32]}]
    p = make_pipeline(m)
    # a file the pipeline didn't write already sits at badge_00's destination
    (project / "badges").mkdir()
    (project / "badges" / "badge_00.png").write_bytes(b"hand-made art")
    p.claim("main", asset_ids=["badge_00"])
    p.register_attempt("badge_00", good_png, "main", PROV)
    p.record_sheet(good_png, ["badge_00"])
    out = p.decide("badge_00", "approve", "agent")
    assert out["staged"] == ["badges/badge_00.png", "badges/badge_00-32.png"]
    moved = out["superseded"][0]
    assert moved["was"] == "badges/badge_00.png"
    assert (project / moved["moved_to"]).read_bytes() == b"hand-made art"
    assert (project / "badges" / "badge_00-32.png").is_file()
    doc = json.loads((project / "art-manifest.json").read_text())
    assert doc["assets"][0]["approved"]["renditions"] == ["badges/badge_00-32.png"]

    # re-approval (after a re-lock sends it back to review) replaces the pipeline's own copy in place
    p.lock_style("user")
    assert p.lock_style("user", "Revised block")["rereview"] == ["badge_00"]
    p.record_sheet(good_png, ["badge_00"])
    again = p.decide("badge_00", "approve", "user")
    assert again["staged"][0] == "badges/badge_00.png" and "superseded" not in again


def test_no_heroes_caps_claims_at_threshold(make_pipeline):
    m = make_manifest(n_assets=5, heroes=0)
    m["settings"]["gate_threshold"] = 2
    p = make_pipeline(m)
    assert len(p.claim("main", n=5)["claimed"]) == 2
    with pytest.raises(PipelineError) as e:
        p.claim("main")
    assert code(e) == E.STYLE_NOT_LOCKED


# ---------------------------------------------------------------- attempts & checks

def test_failed_checks_retry_then_flag(make_pipeline, bad_png):
    p = make_pipeline()
    p.claim("main", asset_ids=["badge_00"])
    r1 = p.register_attempt("badge_00", bad_png, "main", PROV)
    assert r1["status"] == "in_progress" and r1["attempts_left"] == 2
    assert "smaller than master" in r1["checks"]["fail"][0]

    with pytest.raises(PipelineError) as e:
        p.register_attempt("badge_00", bad_png, "main", PROV)
    assert code(e) == E.NO_CAUSE_CHANGE

    p.register_attempt("badge_00", bad_png, "main", PROV, change_from_previous="new seed")
    r3 = p.register_attempt("badge_00", bad_png, "main", PROV, change_from_previous="new reference")
    assert r3["status"] == "flagged" and r3["attempts_left"] == 0

    with pytest.raises(PipelineError) as e:
        p.unflag("badge_00", "agent")
    assert code(e) == E.USER_SIGNOFF_REQUIRED
    out = p.unflag("badge_00", "user", extra_attempts=2)
    assert out == {"asset_id": "badge_00", "status": "pending", "attempts_left": 2}
    packet = p.claim("main", asset_ids=["badge_00"])["claimed"][0]
    assert [a["decision"] for a in packet["previous_attempts"]] == ["failed_checks"] * 3


def test_alpha_rules(make_pipeline, tmp_path):
    m = make_manifest()
    m["assets"][0]["class"] = "sprite"
    m["assets"][0]["overrides"] = {"master": [64, 64]}
    p = make_pipeline(m)
    p.claim("main", n=2)
    opaque = make_png(tmp_path / "opaque.png")
    clear = make_png(tmp_path / "clear.png", alpha=True)
    r = p.register_attempt("badge_00", opaque, "main", PROV)
    assert any("transparent background required" in f for f in r["checks"]["fail"])
    assert p.register_attempt("badge_00", clear, "main", PROV, "cut out bg")["checks"]["pass"]
    r = p.register_attempt("badge_01", clear, "main", PROV)  # badge class forbids alpha
    assert any("fully opaque" in f for f in r["checks"]["fail"])


def test_register_guards(make_pipeline, good_png, tmp_path):
    m = make_manifest()
    m["assets"][1].update({"class": "ui_icon_svg", "destination": "ui/icon.svg"})
    p = make_pipeline(m)
    with pytest.raises(PipelineError) as e:
        p.register_attempt("badge_00", good_png, "main", PROV)
    assert code(e) == E.INVALID_STATE
    p.claim("main", n=2)
    with pytest.raises(PipelineError) as e:
        p.register_attempt("badge_00", tmp_path / "missing.png", "main", PROV)
    assert code(e) == E.SOURCE_NOT_FOUND
    with pytest.raises(PipelineError) as e:
        p.register_attempt("badge_01", good_png, "main", PROV)
    assert code(e) == E.WRONG_FORMAT
    with pytest.raises(PipelineError) as e:
        p.register_attempt("badge_00", good_png, "main", {"route": "magic", "tool": "x"})
    assert code(e) == E.INVALID_ARGUMENT
    svg = tmp_path / "icon.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 44 44">'
                   '<circle cx="22" cy="22" r="16" fill="#22B8B0"/></svg>')
    r = p.register_attempt("badge_01", svg, "main", PROV)
    assert r["status"] == "awaiting_review", r
    assert r["checks"]["metrics"]["renditions"] == {"@1x": "44x44", "@2x": "88x88", "@3x": "132x132"}
    assert (p.root / r["stored"]).is_file()


# ---------------------------------------------------------------- review & decisions

def test_reject_needs_reason_and_feeds_next_packet(make_pipeline, good_png):
    p = make_pipeline()
    p.claim("main", asset_ids=["badge_00"])
    p.register_attempt("badge_00", good_png, "main", PROV)
    with pytest.raises(PipelineError) as e:
        p.decide("badge_00", "approve", "agent")
    assert code(e) == E.NOT_REVIEWED
    p.record_sheet(good_png, ["badge_00"])
    with pytest.raises(PipelineError) as e:
        p.decide("badge_00", "reject", "agent")
    assert code(e) == E.REASON_REQUIRED
    out = p.decide("badge_00", "reject", "user", reason="glyph unreadable at 32 px")
    assert out["status"] == "pending"
    packet = p.claim("sub-2", asset_ids=["badge_00"])["claimed"][0]
    assert packet["previous_attempts"][0]["reason"] == "glyph unreadable at 32 px"
    assert packet["attempts_left"] == 2
    assert "change_from_previous" in packet["next"]


def test_decide_wrong_state(make_pipeline):
    p = make_pipeline()
    with pytest.raises(PipelineError) as e:
        p.decide("badge_00", "approve", "agent")
    assert code(e) == E.INVALID_STATE
    with pytest.raises(PipelineError) as e:
        p.decide("nope", "approve", "agent")
    assert code(e) == E.ASSET_NOT_FOUND


def test_batch_gate(make_pipeline, good_png):
    m = make_manifest(n_assets=6, heroes=0)
    m["settings"]["gate_threshold"] = 2
    p = make_pipeline(m)
    approve(p, "badge_00", good_png)
    p.claim("main", asset_ids=["badge_01"])
    p.register_attempt("badge_01", good_png, "main", PROV)
    p.record_sheet(good_png, ["badge_01"])
    out = p.decide("badge_01", "approve", "agent")
    gate = out["gate_due"]
    assert gate["asset_ids"] == ["badge_00", "badge_01"]

    with pytest.raises(PipelineError) as e:
        p.claim("main")
    assert code(e) == E.GATE_DUE
    with pytest.raises(PipelineError) as e:
        p.pass_gate(gate["gate_id"], "user")
    assert code(e) == E.GATE_NOT_REVIEWED
    with pytest.raises(PipelineError) as e:
        p.record_sheet(good_png, ["badge_00"], gate_id=gate["gate_id"])
    assert code(e) == E.INVALID_ARGUMENT
    p.record_sheet(good_png, ["badge_00", "badge_01"], gate_id=gate["gate_id"])
    with pytest.raises(PipelineError) as e:
        p.pass_gate(gate["gate_id"], "agent")
    assert code(e) == E.USER_SIGNOFF_REQUIRED
    p.pass_gate(gate["gate_id"], "user")
    # Still no lock and no heroes: the threshold also caps starts before a lock.
    with pytest.raises(PipelineError) as e:
        p.claim("main")
    assert code(e) == E.STYLE_NOT_LOCKED
    p.lock_style("user")
    assert p.claim("main")["claimed"][0]["asset_id"] == "badge_02"


# ---------------------------------------------------------------- leases

def test_leases(make_pipeline, good_png, clock):
    p = make_pipeline()
    p.claim("sub-1", asset_ids=["badge_00"])
    with pytest.raises(PipelineError) as e:
        p.register_attempt("badge_00", good_png, "sub-2", PROV)
    assert code(e) == E.LEASED_BY_OTHER
    with pytest.raises(PipelineError) as e:
        p.claim("sub-2", asset_ids=["badge_00"])
    assert code(e) == E.INVALID_STATE
    assert p.claim("sub-1", asset_ids=["badge_00"])["claimed"]  # renew own lease
    clock.advance(minutes=31)
    assert p.status()["leases"][0]["stale"] is True
    assert p.claim("sub-2", asset_ids=["badge_00"])["claimed"][0]["asset_id"] == "badge_00"
    with pytest.raises(PipelineError) as e:
        p.release("badge_00", "sub-1")
    assert code(e) == E.LEASED_BY_OTHER
    assert p.release("badge_00", "sub-2")["status"] == "pending"


# ---------------------------------------------------------------- flags, manifest, history

def test_flag_and_waive(make_pipeline):
    p = make_pipeline()
    p.flag("badge_00", "needs a human illustrator", "agent")
    with pytest.raises(PipelineError) as e:
        p.flag("badge_00", "again", "agent")
    assert code(e) == E.INVALID_STATE
    assert p.unflag("badge_00", "user", action="waive")["status"] == "waived"


def test_manifest_records_provenance(make_pipeline, good_png, project):
    p = make_pipeline()
    p.claim("main", asset_ids=["badge_00"])
    p.register_attempt("badge_00", good_png, "main",
                       {**PROV, "model": None, "seed": 7, "rights": "original (code-authored)"})
    p.record_sheet(good_png, ["badge_00"])
    p.decide("badge_00", "approve", "user")
    doc = json.loads((project / "art-manifest.json").read_text())
    a = doc["assets"][0]
    assert a["status"] == "approved" and a["attempts"] == 1
    assert a["approved"]["file"] == "badges/badge_00.png"  # staged at its destination
    assert a["approved"]["attempt_file"] == ".artpipeline/attempts/badge_00/1/badge_00.png"
    assert (project / "badges" / "badge_00.png").is_file()
    assert a["approved"]["seed"] == 7 and a["approved"]["approved_by"] == "user"
    assert a["approved"]["rights"] == "original (code-authored)"
    kinds = [e["kind"] for e in p.history("badge_00")["events"]]
    assert kinds == ["claim", "attempt", "approve", "stage"]


def test_older_pipeline_is_migrated(make_pipeline, good_png, project):
    import sqlite3
    make_pipeline()
    db = project / ".artpipeline" / "pipeline.db"
    conn = sqlite3.connect(db)
    conn.execute("ALTER TABLE style_locks DROP COLUMN provisional")
    conn.execute("DROP TABLE staged")
    conn.execute("DROP TABLE placements")
    conn.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
    conn.commit()
    conn.close()
    from artpipeline.store import Store
    p = Pipeline(Store.open(project))
    approve(p, "badge_00", good_png, by="user")
    approve(p, "badge_01", good_png, by="user")
    assert p.lock_style("user")["provisional"] is False
    assert (project / "badges" / "badge_00.png").is_file()


def test_forbidden_alpha_is_written_without_an_alpha_channel(make_pipeline, tmp_path, project):
    """Game Center / App Store reject PNGs that have an alpha channel at all, even fully opaque."""
    from PIL import Image
    m = make_manifest(n_assets=1, heroes=0)
    m["classes"]["badge"]["renditions"] = [{"suffix": "-32", "size": [32, 32]}]
    p = make_pipeline(m)
    src = tmp_path / "rgba-opaque.png"
    Image.new("RGBA", (64, 64), (34, 184, 176, 255)).save(src)
    approve(p, "badge_00", src)
    for f in ("badges/badge_00.png", "badges/badge_00-32.png"):
        assert Image.open(project / f).mode == "RGB", f
