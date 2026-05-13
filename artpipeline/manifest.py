from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class Asset:
    id: str
    status: str
    type: str
    destination: str
    dimensions: list[int]
    prompt: str
    acceptance_criteria: list
    rejection_reason: Optional[str] = None
    retry_count: int = 0
    filed_path: Optional[str] = None
    species: Optional[str] = None
    # Multi-resolution support: maps res_key -> {destination, dimensions, filed_path}
    # The root destination/dimensions/filed_path represent the canonical (generated) resolution.
    derived_resolutions: Optional[dict] = None
    # When True, the asset cannot be produced directly by an image generator.
    # artpipeline files a PNG mockup instead; destination must end in _mockup.png.
    mockup_only: bool = False
    # When True, `artpipeline file` post-processes the source: near-white pixels
    # are converted to alpha so the resulting PNG has a real transparent background.
    # Set this for any asset whose acceptance criteria require transparency but whose
    # image generator (e.g. ChatGPT) flattens the alpha channel on export.
    transparent_background: bool = False


@dataclass
class Manifest:
    brief: str
    project: str
    direction: str
    assets: dict = field(default_factory=dict)

    def get_asset(self, asset_id: str) -> Asset:
        if asset_id not in self.assets:
            valid = sorted(self.assets.keys())
            raise KeyError(f"Asset '{asset_id}' not found. Valid IDs: {valid}")
        return self.assets[asset_id]


def load(path: Path) -> Manifest:
    data = json.loads(path.read_text(encoding="utf-8"))
    assets = {}
    for k, v in data["assets"].items():
        v.pop("resolution", None)  # drop deprecated per-resolution field if present
        assets[k] = Asset(**v)
    return Manifest(
        brief=data["brief"],
        project=data["project"],
        direction=data["direction"],
        assets=assets,
    )


def save(m: Manifest, path: Path) -> None:
    data = {
        "brief": m.brief,
        "project": m.project,
        "direction": m.direction,
        "assets": {k: asdict(v) for k, v in m.assets.items()},
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
