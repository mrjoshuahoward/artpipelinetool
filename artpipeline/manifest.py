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
    resolution: Optional[str] = None


@dataclass
class Manifest:
    brief: str
    project: str
    direction: str
    assets: dict[str, Asset] = field(default_factory=dict)

    def get_asset(self, asset_id: str) -> Asset:
        if asset_id not in self.assets:
            valid = sorted(self.assets.keys())
            raise KeyError(f"Asset '{asset_id}' not found. Valid IDs: {valid}")
        return self.assets[asset_id]


def load(path: Path) -> Manifest:
    data = json.loads(path.read_text(encoding="utf-8"))
    assets = {k: Asset(**v) for k, v in data["assets"].items()}
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
