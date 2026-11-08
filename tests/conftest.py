from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml
from PIL import Image

from artpipeline.pipeline import Pipeline


class FakeClock:
    def __init__(self) -> None:
        self.t = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        self.t += timedelta(microseconds=1)  # strictly increasing timestamps
        return self.t

    def advance(self, **kw: Any) -> None:
        self.t += timedelta(**kw)


def make_manifest(n_assets: int = 4, heroes: int = 2, **overrides: Any) -> dict[str, Any]:
    assets = []
    for i in range(n_assets):
        assets.append({
            "id": f"badge_{i:02d}",
            "class": "badge",
            "subject": f"Badge number {i}",
            "acceptance_criteria": ["Reads at 64 px", "Uses only palette colours"],
            "destination": f"badges/badge_{i:02d}.png",
            "hero": i < heroes,
            "group": "even" if i % 2 == 0 else "odd",
        })
    m: dict[str, Any] = {
        "version": 2,
        "project": "Sorting Line",
        "direction": "Factory Floor",
        "style": {"block": "Flat vector, 4px strokes, no gradients.",
                  "palette": ["#22B8B0", "#F2C14E", "#23282B"],
                  "backgrounds": ["#23282B", "#49606B"]},
        "settings": {"max_attempts": 3, "gate_threshold": 15, "lease_minutes": 30},
        "classes": {"badge": {"format": "png", "master": [64, 64], "alpha": "forbidden",
                              "display_sizes": [64, 32]}},
        "assets": assets,
    }
    m.update(overrides)
    return m


def write_brief(path: Path, manifest: dict[str, Any], markdown: bool = True) -> Path:
    body = yaml.safe_dump(manifest, sort_keys=False)
    if markdown:
        path.write_text(f"# Brief\n\nProse.\n\n## Asset Manifest\n\n```yaml\n{body}```\n", encoding="utf-8")
    else:
        path.write_text(body, encoding="utf-8")
    return path


def make_png(path: Path, size=(64, 64), alpha: bool = False, color=(34, 184, 176)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if alpha:
        img = Image.new("RGBA", size, (0, 0, 0, 0))
        w, h = size
        for x in range(w // 4, 3 * w // 4):
            for y in range(h // 4, 3 * h // 4):
                img.putpixel((x, y), (*color, 255))
    else:
        img = Image.new("RGB", size, color)
    img.save(path)
    return path


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    d = tmp_path / "project"
    d.mkdir()
    return d


@pytest.fixture
def good_png(tmp_path: Path) -> Path:
    return make_png(tmp_path / "gen" / "good.png")


@pytest.fixture
def bad_png(tmp_path: Path) -> Path:
    return make_png(tmp_path / "gen" / "bad.png", size=(32, 32))  # smaller than master: refused


@pytest.fixture
def make_pipeline(project: Path, clock: FakeClock):
    def _make(manifest: dict[str, Any] | None = None) -> Pipeline:
        brief = write_brief(project / "brief.md", manifest or make_manifest())
        p, _ = Pipeline.init(brief, clock=clock)
        return p
    return _make


PROV = {"route": "code_native", "tool": "Claude SVG", "prompt": "badge glyph"}


def approve(p: Pipeline, asset_id: str, png: Path, agent: str = "main", by: str = "agent") -> None:
    """Claim → register (passing) → sheet → approve."""
    p.claim(agent, asset_ids=[asset_id])
    res = p.register_attempt(asset_id, png, agent, PROV)
    assert res["status"] == "awaiting_review", res
    p.record_sheet(png, [asset_id])
    p.decide(asset_id, "approve", by)
