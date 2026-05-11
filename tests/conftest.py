import json
import pytest
from pathlib import Path

SAMPLE_BRIEF_YAML = """\
project: TestProject
direction: TestDirection
assets:
  - id: bird_crane_1x
    type: bird_sprite
    species: crane
    resolution: 1x
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
    "id": "bird_crane_1x",
    "status": "pending",
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

SAMPLE_MANIFEST_DATA = {
    "brief": "test-brief.md",
    "project": "TestProject",
    "direction": "TestDirection",
    "assets": {"bird_crane_1x": SAMPLE_ASSET},
}


@pytest.fixture
def tmp_project(tmp_path):
    return tmp_path


@pytest.fixture
def brief_file(tmp_project):
    path = tmp_project / "test-brief.md"
    path.write_text(SAMPLE_BRIEF_TEXT, encoding="utf-8")
    return path


@pytest.fixture
def pipeline_file(tmp_project):
    path = tmp_project / "pipeline.json"
    path.write_text(json.dumps(SAMPLE_MANIFEST_DATA, indent=2), encoding="utf-8")
    return path
