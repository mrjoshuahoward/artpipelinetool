import json
import pytest
from pathlib import Path
from click.testing import CliRunner
from artpipeline.cli import main


@pytest.fixture
def runner():
    return CliRunner()


def test_parse_creates_pipeline_json(runner, brief_file, tmp_project):
    result = runner.invoke(main, ["parse", str(brief_file)], catch_exceptions=False)
    assert result.exit_code == 0
    pipeline = tmp_project / "pipeline.json"
    assert pipeline.exists()
    data = json.loads(pipeline.read_text())
    assert data["project"] == "TestProject"
    assert "bird_crane_1x" in data["assets"]


def test_parse_output_json(runner, brief_file):
    result = runner.invoke(main, ["parse", str(brief_file)], catch_exceptions=False)
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["project"] == "TestProject"
    assert len(output["assets"]) == 1


def test_parse_preserves_existing_status(runner, brief_file, tmp_project):
    # First parse
    runner.invoke(main, ["parse", str(brief_file)], catch_exceptions=False)
    pipeline = tmp_project / "pipeline.json"
    data = json.loads(pipeline.read_text())
    data["assets"]["bird_crane_1x"]["status"] = "approved"
    pipeline.write_text(json.dumps(data, indent=2))
    # Re-parse — status should be preserved
    runner.invoke(main, ["parse", str(brief_file)], catch_exceptions=False)
    data2 = json.loads(pipeline.read_text())
    assert data2["assets"]["bird_crane_1x"]["status"] == "approved"


def test_parse_missing_manifest_section_fails(runner, tmp_project):
    bad_brief = tmp_project / "bad.md"
    bad_brief.write_text("# No manifest", encoding="utf-8")
    result = runner.invoke(main, ["parse", str(bad_brief)])
    assert result.exit_code != 0


# --- Task 6: status ---

def test_status_all(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    result = runner.invoke(main, ["status"], catch_exceptions=False)
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert "pending" in output
    assert any(a["id"] == "bird_crane_1x" for a in output["pending"])


def test_status_single_asset(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    result = runner.invoke(main, ["status", "--asset", "bird_crane_1x"], catch_exceptions=False)
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["id"] == "bird_crane_1x"
    assert output["status"] == "pending"


def test_status_unknown_asset(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    result = runner.invoke(main, ["status", "--asset", "nonexistent"])
    assert result.exit_code != 0


# --- Task 7: next ---

def test_next_returns_first_pending(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    result = runner.invoke(main, ["next"], catch_exceptions=False)
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["asset_id"] == "bird_crane_1x"
    assert "artpipeline prompt bird_crane_1x" in output["next_command"]


def test_next_with_stage_filter(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    result = runner.invoke(main, ["next", "--stage", "prompted"], catch_exceptions=False)
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["asset_id"] is None


def test_next_all_approved(runner, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    import json as _json
    from tests.conftest import SAMPLE_MANIFEST_DATA
    import copy
    data = copy.deepcopy(SAMPLE_MANIFEST_DATA)
    data["assets"]["bird_crane_1x"]["status"] = "approved"
    (tmp_project / "pipeline.json").write_text(_json.dumps(data, indent=2))
    result = runner.invoke(main, ["next"], catch_exceptions=False)
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["asset_id"] is None
    assert output["message"] == "All assets approved."


# --- Task 8: prompt ---

def test_prompt_returns_prompt(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    result = runner.invoke(main, ["prompt", "bird_crane_1x"], catch_exceptions=False)
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert "Sandhill Crane" in output["prompt"]
    assert output["retry_count"] == 0


def test_prompt_sets_status_prompted(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    runner.invoke(main, ["prompt", "bird_crane_1x"], catch_exceptions=False)
    import json as _json
    data = _json.loads((tmp_project / "pipeline.json").read_text())
    assert data["assets"]["bird_crane_1x"]["status"] == "prompted"


def test_prompt_retry_prepends_revision(runner, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    import json as _json, copy
    from tests.conftest import SAMPLE_MANIFEST_DATA
    data = copy.deepcopy(SAMPLE_MANIFEST_DATA)
    data["assets"]["bird_crane_1x"]["status"] = "rejected"
    data["assets"]["bird_crane_1x"]["rejection_reason"] = "neck not visible"
    (tmp_project / "pipeline.json").write_text(_json.dumps(data, indent=2))
    result = runner.invoke(main, ["prompt", "bird_crane_1x", "--retry"], catch_exceptions=False)
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert "neck not visible" in output["prompt"]
    assert "REVISION" in output["prompt"]


def test_prompt_unknown_asset_fails(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    result = runner.invoke(main, ["prompt", "nonexistent"])
    assert result.exit_code != 0


# --- Task 9: file ---

def test_file_copies_image(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    src = tmp_project / "downloaded.png"
    src.write_bytes(b"fake png data")
    result = runner.invoke(main, ["file", str(src), "bird_crane_1x"], catch_exceptions=False)
    assert result.exit_code == 0
    dest = tmp_project / "art" / "birds" / "crane@1x.png"
    assert dest.exists()
    assert dest.read_bytes() == b"fake png data"


def test_file_sets_status_filed(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    src = tmp_project / "downloaded.png"
    src.write_bytes(b"fake")
    runner.invoke(main, ["file", str(src), "bird_crane_1x"], catch_exceptions=False)
    import json as _json
    data = _json.loads((tmp_project / "pipeline.json").read_text())
    assert data["assets"]["bird_crane_1x"]["status"] == "filed"
    assert data["assets"]["bird_crane_1x"]["filed_path"] is not None


def test_file_missing_source_fails(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    result = runner.invoke(main, ["file", str(tmp_project / "missing.png"), "bird_crane_1x"])
    assert result.exit_code != 0


def test_file_wrong_extension_fails(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    src = tmp_project / "image.jpg"
    src.write_bytes(b"fake")
    result = runner.invoke(main, ["file", str(src), "bird_crane_1x"])
    assert result.exit_code != 0


# --- Task 10: review ---

def test_review_outputs_checks_and_criteria(runner, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    import json as _json, copy
    from tests.conftest import SAMPLE_MANIFEST_DATA
    data = copy.deepcopy(SAMPLE_MANIFEST_DATA)
    data["assets"]["bird_crane_1x"]["status"] = "filed"
    art_dir = tmp_project / "art" / "birds"
    art_dir.mkdir(parents=True)
    dest = art_dir / "crane@1x.png"
    dest.write_bytes(b"fake")
    data["assets"]["bird_crane_1x"]["filed_path"] = "art/birds/crane@1x.png"
    (tmp_project / "pipeline.json").write_text(_json.dumps(data, indent=2))
    result = runner.invoke(main, ["review", "bird_crane_1x"], catch_exceptions=False)
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert "checks" in output
    assert output["checks"]["file_exists"] is True
    assert "acceptance_criteria" in output
    assert len(output["acceptance_criteria"]) == 2
    assert output["visual_review_required"] is True


def test_review_unfiled_asset_fails(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    result = runner.invoke(main, ["review", "bird_crane_1x"])
    assert result.exit_code != 0


# --- Task 11: approve and reject ---

def _make_filed_pipeline(tmp_project):
    import json as _json
    data = {
        "brief": "test-brief.md",
        "project": "TestProject",
        "direction": "TestDirection",
        "assets": {
            "bird_crane_1x": {
                "id": "bird_crane_1x",
                "status": "filed",
                "type": "bird_sprite",
                "species": "crane",
                "resolution": "1x",
                "destination": "art/birds/crane@1x.png",
                "dimensions": [48, 48],
                "prompt": "Top-down silhouette of a Sandhill Crane viewed from above.",
                "acceptance_criteria": ["Silhouette only, no internal detail", "Transparent background"],
                "rejection_reason": None,
                "retry_count": 0,
                "filed_path": None,
            }
        },
    }
    (tmp_project / "pipeline.json").write_text(_json.dumps(data, indent=2))


def test_approve_sets_status(runner, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    _make_filed_pipeline(tmp_project)
    result = runner.invoke(main, ["approve", "bird_crane_1x"], catch_exceptions=False)
    assert result.exit_code == 0
    import json as _json
    data = _json.loads((tmp_project / "pipeline.json").read_text())
    assert data["assets"]["bird_crane_1x"]["status"] == "approved"


def test_reject_sets_status_and_reason(runner, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    _make_filed_pipeline(tmp_project)
    result = runner.invoke(
        main, ["reject", "bird_crane_1x", "--reason", "neck not visible"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    import json as _json
    data = _json.loads((tmp_project / "pipeline.json").read_text())
    assert data["assets"]["bird_crane_1x"]["status"] == "rejected"
    assert data["assets"]["bird_crane_1x"]["rejection_reason"] == "neck not visible"
    assert data["assets"]["bird_crane_1x"]["retry_count"] == 1


def test_reject_without_reason_fails(runner, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    _make_filed_pipeline(tmp_project)
    result = runner.invoke(main, ["reject", "bird_crane_1x"])
    assert result.exit_code != 0


def test_reject_then_prompt_retry_transitions(runner, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    _make_filed_pipeline(tmp_project)
    runner.invoke(main, ["reject", "bird_crane_1x", "--reason", "neck not visible"],
                  catch_exceptions=False)
    result = runner.invoke(main, ["prompt", "bird_crane_1x", "--retry"], catch_exceptions=False)
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert "neck not visible" in output["prompt"]
    import json as _json
    data = _json.loads((tmp_project / "pipeline.json").read_text())
    assert data["assets"]["bird_crane_1x"]["status"] == "prompted"
