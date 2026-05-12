import json
import pytest
from pathlib import Path
from artpipeline import manifest


def test_load_manifest(pipeline_file):
    m = manifest.load(pipeline_file)
    assert m.project == "TestProject"
    assert m.direction == "TestDirection"
    assert "bird_crane" in m.assets


def test_load_asset_fields(pipeline_file):
    m = manifest.load(pipeline_file)
    a = m.assets["bird_crane"]
    assert a.id == "bird_crane"
    assert a.status == "pending"
    assert a.type == "bird_sprite"
    assert a.dimensions == [48, 48]
    assert a.retry_count == 0
    assert a.rejection_reason is None
    assert a.filed_path is None
    assert a.derived_resolutions is None


def test_save_and_reload(tmp_project, pipeline_file):
    m = manifest.load(pipeline_file)
    m.assets["bird_crane"].status = "prompted"
    out = tmp_project / "out.json"
    manifest.save(m, out)
    m2 = manifest.load(out)
    assert m2.assets["bird_crane"].status == "prompted"


def test_get_asset_found(pipeline_file):
    m = manifest.load(pipeline_file)
    a = m.get_asset("bird_crane")
    assert a.id == "bird_crane"


def test_get_asset_not_found(pipeline_file):
    m = manifest.load(pipeline_file)
    with pytest.raises(KeyError, match="not found"):
        m.get_asset("nonexistent")


def test_save_preserves_order(tmp_project, pipeline_file):
    m = manifest.load(pipeline_file)
    out = tmp_project / "out.json"
    manifest.save(m, out)
    data = json.loads(out.read_text())
    assert list(data["assets"].keys()) == ["bird_crane"]


def test_load_drops_deprecated_resolution_field(tmp_project):
    """Old pipeline.json files with a 'resolution' field should load without error."""
    old_data = {
        "brief": "test.md",
        "project": "P",
        "direction": "D",
        "assets": {
            "bird_crane_1x": {
                "id": "bird_crane_1x",
                "status": "pending",
                "type": "bird_sprite",
                "species": "crane",
                "resolution": "1x",
                "destination": "art/birds/crane@1x.png",
                "dimensions": [48, 48],
                "prompt": "test",
                "acceptance_criteria": [],
                "rejection_reason": None,
                "retry_count": 0,
                "filed_path": None,
                "derived_resolutions": None,
            }
        },
    }
    p = tmp_project / "pipeline.json"
    p.write_text(json.dumps(old_data), encoding="utf-8")
    m = manifest.load(p)
    a = m.assets["bird_crane_1x"]
    assert not hasattr(a, "resolution") or a.derived_resolutions is None


def test_save_and_reload_derived_resolutions(tmp_project, pipeline_file):
    m = manifest.load(pipeline_file)
    m.assets["bird_crane"].derived_resolutions = {
        "2x": {"destination": "art/birds/crane@2x.png", "dimensions": [96, 96], "filed_path": None}
    }
    out = tmp_project / "out.json"
    manifest.save(m, out)
    m2 = manifest.load(out)
    assert m2.assets["bird_crane"].derived_resolutions["2x"]["dimensions"] == [96, 96]
