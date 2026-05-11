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
