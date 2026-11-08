"""Read a brief: the '## Asset Manifest' YAML block in a Markdown brief, or a standalone YAML file."""
from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import ValidationError

from artpipeline import errors as E
from artpipeline.errors import PipelineError
from artpipeline.schema import BriefManifest

MANIFEST_HEADING = re.compile(r"^#{1,6}\s+Asset Manifest\s*$", re.MULTILINE)
YAML_FENCE = re.compile(r"^```ya?ml[ \t]*\r?\n(.*?)^```", re.DOTALL | re.MULTILINE)


def load_brief(path: Path) -> BriefManifest:
    if not path.is_file():
        raise PipelineError(E.BRIEF_NOT_FOUND, f"Brief not found: {path}")
    text = path.read_text(encoding="utf-8")
    raw_yaml = text if path.suffix.lower() in (".yaml", ".yml") else _extract_block(text, path)
    try:
        data = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as e:
        raise PipelineError(E.BRIEF_INVALID, f"Asset manifest is not valid YAML: {e}") from e
    return parse_manifest(data)


def parse_manifest(data: object) -> BriefManifest:
    if not isinstance(data, dict):
        raise PipelineError(E.BRIEF_INVALID, "Asset manifest must be a YAML mapping.")
    if data.get("version") != 2:
        raise PipelineError(
            E.BRIEF_VERSION,
            "Asset manifest must declare 'version: 2'.",
            hint="v1 manifests (bird_sprite/ui_glyph/app_icon types) are not supported. "
            "Regenerate the manifest with the casual-mobile-art-director skill.",
        )
    try:
        return BriefManifest.model_validate(data)
    except ValidationError as e:
        problems = [
            {"at": ".".join(str(p) for p in err["loc"]) or "(root)", "problem": err["msg"]}
            for err in e.errors()
        ]
        raise PipelineError(
            E.BRIEF_INVALID,
            f"Asset manifest has {len(problems)} problem(s).",
            hint="Fix each listed field in the brief and run init again.",
            problems=problems,
        ) from None


def _extract_block(text: str, path: Path) -> str:
    m = MANIFEST_HEADING.search(text)
    if not m:
        raise PipelineError(
            E.BRIEF_NO_MANIFEST,
            f"{path.name} has no '## Asset Manifest' section.",
            hint="Add a '## Asset Manifest' heading followed by a ```yaml block, or pass a .yaml file.",
        )
    fence = YAML_FENCE.search(text, m.end())
    if not fence:
        raise PipelineError(
            E.BRIEF_NO_MANIFEST, "Found '## Asset Manifest' but no ```yaml block after it."
        )
    return fence.group(1)
