import json
import pytest
from pathlib import Path
from artpipeline import manifest


def test_load_manifest(pipeline_file):
    m = manifest.load(pipeline_file)
    assert m.project == "TestProject"
    assert m.direction == "TestDirection"
    assert "bird_crane_1x" in m.assets


def test_load_asset_fields(pipeline_file):
    m = manifest.load(pipeline_file)
    a = m.assets["bird_crane_1x"]
    assert a.id == "bird_crane_1x"
    assert a.status == "pending"
    assert a.type == "bird_sprite"
    assert a.dimensions == [48, 48]
    assert a.retry_count == 0
    assert a.rejection_reason is None
    assert a.filed_path is None


def test_save_and_reload(tmp_project, pipeline_file):
    m = manifest.load(pipeline_file)
    m.assets["bird_crane_1x"].status = "prompted"
    out = tmp_project / "out.json"
    manifest.save(m, out)
    m2 = manifest.load(out)
    assert m2.assets["bird_crane_1x"].status == "prompted"


def test_get_asset_found(pipeline_file):
    m = manifest.load(pipeline_file)
    a = m.get_asset("bird_crane_1x")
    assert a.id == "bird_crane_1x"


def test_get_asset_not_found(pipeline_file):
    m = manifest.load(pipeline_file)
    with pytest.raises(KeyError, match="not found"):
        m.get_asset("nonexistent")


def test_save_preserves_order(tmp_project, pipeline_file):
    m = manifest.load(pipeline_file)
    out = tmp_project / "out.json"
    manifest.save(m, out)
    data = json.loads(out.read_text())
    assert list(data["assets"].keys()) == ["bird_crane_1x"]
