import pytest
from artpipeline import parser


def test_extract_asset_manifest(brief_file):
    data = parser.parse_brief(brief_file)
    assert data["project"] == "TestProject"
    assert len(data["assets"]) == 1
    assert data["assets"][0]["id"] == "bird_crane_1x"


def test_extract_asset_fields(brief_file):
    data = parser.parse_brief(brief_file)
    asset = data["assets"][0]
    assert asset["type"] == "bird_sprite"
    assert asset["dimensions"] == [48, 48]
    assert "Silhouette only, no internal detail" in asset["acceptance_criteria"]


def test_missing_manifest_section(tmp_project):
    brief = tmp_project / "no-manifest.md"
    brief.write_text("# Brief\n\nNo manifest section here.", encoding="utf-8")
    with pytest.raises(ValueError, match="Asset Manifest"):
        parser.parse_brief(brief)


def test_missing_yaml_block(tmp_project):
    brief = tmp_project / "bad-manifest.md"
    brief.write_text("# Brief\n\n## Asset Manifest\n\nNo YAML block.", encoding="utf-8")
    with pytest.raises(ValueError, match="fenced YAML"):
        parser.parse_brief(brief)


def test_extract_from_text():
    text = (
        "# Brief\n\n## Asset Manifest\n```yaml\n"
        "project: Foo\ndirection: Bar\nassets: []\n"
        "```\n"
    )
    data = parser.extract_asset_manifest(text)
    assert data["project"] == "Foo"
    assert data["assets"] == []


def test_crlf_line_endings(tmp_project):
    """Brief with Windows CRLF line endings must parse correctly."""
    text = (
        "# Brief\r\n\r\n## Asset Manifest\r\n```yaml\r\n"
        "project: Foo\r\ndirection: Bar\r\nassets: []\r\n"
        "```\r\n"
    )
    data = parser.extract_asset_manifest(text)
    assert data["project"] == "Foo"


def test_empty_yaml_block_raises(tmp_project):
    """An empty YAML block raises a clear ValueError."""
    text = "# Brief\n\n## Asset Manifest\n```yaml\n```\n"
    with pytest.raises(ValueError, match="did not parse to a mapping"):
        parser.extract_asset_manifest(text)
