from __future__ import annotations
import re
import yaml
from pathlib import Path

MANIFEST_HEADING = "## Asset Manifest"
_YAML_FENCE = re.compile(r"```yaml\n(.*?)```", re.DOTALL)


def extract_asset_manifest(text: str) -> dict:
    heading_idx = text.find(MANIFEST_HEADING)
    if heading_idx == -1:
        raise ValueError(
            f"Brief is missing the '{MANIFEST_HEADING}' section. "
            "Regenerate the brief using the art-director skill — it must include "
            "a structured YAML manifest block."
        )
    after_heading = text[heading_idx + len(MANIFEST_HEADING):]
    match = _YAML_FENCE.search(after_heading)
    if not match:
        raise ValueError(
            f"Found '{MANIFEST_HEADING}' but no fenced YAML block follows it."
        )
    return yaml.safe_load(match.group(1))


def parse_brief(brief_path: Path) -> dict:
    text = brief_path.read_text(encoding="utf-8")
    return extract_asset_manifest(text)
