# artpipeline CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python CLI tool (`artpipeline`) that helps Claude Cowork drive an art asset production pipeline — parsing art briefs, serving image-gen prompts, filing generated images, and tracking per-asset status through approval.

**Architecture:** A Click-based CLI with four focused modules: `manifest.py` owns the `pipeline.json` data model and all status transitions; `parser.py` extracts the structured YAML block from art briefs; `review.py` runs programmatic image checks; and `cli.py` is the thin command layer that wires them together. All commands output JSON to stdout; errors go to stderr with non-zero exit codes.

**Tech Stack:** Python 3.10+, Click 8.x, Pillow 10.x (optional, for dimension/alpha checks), pytest 8.x

---

## File Map

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package config, entry point, optional deps |
| `artpipeline/__init__.py` | Package marker |
| `artpipeline/manifest.py` | `pipeline.json` schema, load/save, Asset dataclass |
| `artpipeline/parser.py` | Extract `## Asset Manifest` YAML from brief |
| `artpipeline/review.py` | Programmatic image checks (exists, dimensions, alpha) |
| `artpipeline/cli.py` | All 8 Click commands + main group |
| `tests/conftest.py` | Shared fixtures (tmp_path, sample brief, sample manifest) |
| `tests/test_manifest.py` | Manifest load/save/status tests |
| `tests/test_parser.py` | Brief YAML extraction tests |
| `tests/test_review.py` | Image check tests |
| `tests/test_cli.py` | CLI integration tests via Click CliRunner |
| `~/.claude/skills/art-director/SKILL.md` | Add `## Asset Manifest` emission instruction |

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `artpipeline/__init__.py`
- Create: `artpipeline/manifest.py` (stub)
- Create: `artpipeline/parser.py` (stub)
- Create: `artpipeline/review.py` (stub)
- Create: `artpipeline/cli.py` (stub)
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Initialise git repo**

```bash
cd C:\Users\Joshu\c.artpipelinetool
git init
```

Expected: `Initialized empty Git repository`

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "artpipeline"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["click>=8.1"]

[project.optional-dependencies]
review = ["Pillow>=10.0"]
dev = ["pytest>=8.0", "click>=8.1", "Pillow>=10.0"]

[project.scripts]
artpipeline = "artpipeline.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 3: Create package stubs**

`artpipeline/__init__.py` — empty file.

`artpipeline/manifest.py`:
```python
# pipeline.json data model and persistence
```

`artpipeline/parser.py`:
```python
# Art brief YAML block extraction
```

`artpipeline/review.py`:
```python
# Programmatic image checks
```

`artpipeline/cli.py`:
```python
import click

@click.group()
@click.option("--human", is_flag=True, help="Human-readable output (dev only)")
@click.pass_context
def main(ctx, human):
    ctx.ensure_object(dict)
    ctx.obj["human"] = human
```

`tests/__init__.py` — empty file.

- [ ] **Step 4: Write `tests/conftest.py`**

```python
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

SAMPLE_BRIEF_TEXT = f"""\
# Test Brief

Some prose.

## Asset Manifest
```yaml
{SAMPLE_BRIEF_YAML}```
"""

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
```

- [ ] **Step 5: Install in dev mode**

```bash
pip install -e ".[dev]"
```

Expected: Successfully installed artpipeline-0.1.0

- [ ] **Step 6: Verify CLI entrypoint exists**

```bash
artpipeline --help
```

Expected output contains: `Usage: artpipeline [OPTIONS] COMMAND [ARGS]...`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml artpipeline/ tests/
git commit -m "chore: scaffold artpipeline project"
```

---

## Task 2: `manifest.py` — Data Model and Persistence

**Files:**
- Modify: `artpipeline/manifest.py`
- Create: `tests/test_manifest.py`

- [ ] **Step 1: Write failing tests**

`tests/test_manifest.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_manifest.py -v
```

Expected: ERRORS — `cannot import name 'manifest'` or similar

- [ ] **Step 3: Implement `manifest.py`**

```python
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
    dimensions: list
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
    assets: dict = field(default_factory=dict)

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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_manifest.py -v
```

Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add artpipeline/manifest.py tests/test_manifest.py
git commit -m "feat: add manifest data model and persistence"
```

---

## Task 3: `parser.py` — Brief YAML Extraction

**Files:**
- Modify: `artpipeline/parser.py`
- Create: `tests/test_parser.py`

- [ ] **Step 1: Write failing tests**

`tests/test_parser.py`:
```python
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
    assert "Silhouette only" in asset["acceptance_criteria"]


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
    text = """\
# Brief

## Asset Manifest
```yaml
project: Foo
direction: Bar
assets: []
```
"""
    data = parser.extract_asset_manifest(text)
    assert data["project"] == "Foo"
    assert data["assets"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_parser.py -v
```

Expected: ERRORS — functions not defined

- [ ] **Step 3: Implement `parser.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_parser.py -v
```

Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add artpipeline/parser.py tests/test_parser.py
git commit -m "feat: add brief YAML parser"
```

---

## Task 4: `review.py` — Programmatic Image Checks

**Files:**
- Modify: `artpipeline/review.py`
- Create: `tests/test_review.py`

- [ ] **Step 1: Write failing tests**

`tests/test_review.py`:
```python
import pytest
from pathlib import Path
from artpipeline import review


def test_file_exists_true(tmp_path):
    f = tmp_path / "img.png"
    f.write_bytes(b"fake")
    assert review.check_file_exists(f) is True


def test_file_exists_false(tmp_path):
    assert review.check_file_exists(tmp_path / "missing.png") is False


def test_run_checks_missing_file(tmp_path):
    result = review.run_checks(tmp_path / "missing.png", [48, 48])
    assert result["file_exists"] is False
    assert result["dimensions_correct"] is None
    assert result["has_alpha"] is None


def test_run_checks_existing_png(tmp_path):
    # Create a minimal valid 48x48 RGBA PNG using Pillow
    pytest.importorskip("PIL")
    from PIL import Image
    img_path = tmp_path / "test.png"
    img = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
    img.save(img_path)
    result = review.run_checks(img_path, [48, 48])
    assert result["file_exists"] is True
    assert result["dimensions_correct"] is True
    assert result["has_alpha"] is True


def test_run_checks_wrong_dimensions(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image
    img_path = tmp_path / "test.png"
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    img.save(img_path)
    result = review.run_checks(img_path, [48, 48])
    assert result["dimensions_correct"] is False


def test_run_checks_no_alpha(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image
    img_path = tmp_path / "test.png"
    img = Image.new("RGB", (48, 48), (255, 255, 255))
    img.save(img_path)
    result = review.run_checks(img_path, [48, 48])
    assert result["has_alpha"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_review.py -v
```

Expected: ERRORS — functions not defined

- [ ] **Step 3: Implement `review.py`**

```python
from __future__ import annotations
from pathlib import Path
from typing import Optional


def check_file_exists(path: Path) -> bool:
    return path.exists() and path.is_file()


def check_dimensions(path: Path, expected: list) -> Optional[bool]:
    try:
        from PIL import Image
        with Image.open(path) as img:
            return list(img.size) == list(expected)
    except ImportError:
        return None


def check_has_alpha(path: Path) -> Optional[bool]:
    try:
        from PIL import Image
        with Image.open(path) as img:
            return img.mode in ("RGBA", "LA", "PA")
    except ImportError:
        return None


def run_checks(filed_path: Path, expected_dimensions: list) -> dict:
    exists = check_file_exists(filed_path)
    return {
        "file_exists": exists,
        "dimensions_correct": check_dimensions(filed_path, expected_dimensions) if exists else None,
        "has_alpha": check_has_alpha(filed_path) if exists else None,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_review.py -v
```

Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add artpipeline/review.py tests/test_review.py
git commit -m "feat: add programmatic image review checks"
```

---

## Task 5: `parse` Command

**Files:**
- Modify: `artpipeline/cli.py`
- Modify: `tests/test_cli.py` (create)

- [ ] **Step 1: Write failing test**

`tests/test_cli.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_cli.py::test_parse_creates_pipeline_json tests/test_cli.py::test_parse_output_json -v
```

Expected: FAIL — `parse` command not registered

- [ ] **Step 3: Implement `parse` command in `cli.py`**

Add to `cli.py` (keep existing `main` group, add below it):

```python
import json
import sys
from pathlib import Path
from artpipeline import manifest, parser


def _emit(data, human: bool):
    if human:
        click.echo(json.dumps(data, indent=2))
    else:
        click.echo(json.dumps(data))


@main.command()
@click.argument("brief", type=click.Path(exists=True, path_type=Path))
@click.pass_context
def parse(ctx, brief):
    """Parse an art brief and create pipeline.json."""
    try:
        raw = parser.parse_brief(brief)
    except ValueError as e:
        click.echo(str(e), err=True)
        sys.exit(1)

    pipeline_path = brief.parent / "pipeline.json"

    existing = {}
    if pipeline_path.exists():
        try:
            existing_manifest = manifest.load(pipeline_path)
            existing = existing_manifest.assets
        except Exception:
            pass

    assets = {}
    for entry in raw.get("assets", []):
        asset_id = entry["id"]
        if asset_id in existing:
            assets[asset_id] = existing[asset_id]
        else:
            assets[asset_id] = manifest.Asset(
                id=asset_id,
                status="pending",
                type=entry["type"],
                destination=entry["destination"],
                dimensions=entry["dimensions"],
                prompt=entry["prompt"],
                acceptance_criteria=entry["acceptance_criteria"],
                species=entry.get("species"),
                resolution=entry.get("resolution"),
            )

    m = manifest.Manifest(
        brief=brief.name,
        project=raw["project"],
        direction=raw["direction"],
        assets=assets,
    )
    manifest.save(m, pipeline_path)

    output = {
        "project": m.project,
        "direction": m.direction,
        "pipeline": str(pipeline_path),
        "assets": [
            {"id": a.id, "type": a.type, "status": a.status}
            for a in m.assets.values()
        ],
    }
    _emit(output, ctx.obj["human"])
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_cli.py -k "parse" -v
```

Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add artpipeline/cli.py tests/test_cli.py
git commit -m "feat: add parse command"
```

---

## Task 6: `status` Command

**Files:**
- Modify: `artpipeline/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_cli.py`:
```python
def test_status_all(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    result = runner.invoke(main, ["status"], catch_exceptions=False)
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert "pending" in output
    assert any(a["id"] == "bird_crane_1x" for a in output["pending"])


def test_status_single_asset(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    result = runner.invoke(main, ["status", "--asset", "bird_crane_1x"], catch_exceptions=False)
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["id"] == "bird_crane_1x"
    assert output["status"] == "pending"


def test_status_unknown_asset(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    result = runner.invoke(main, ["status", "--asset", "nonexistent"])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_cli.py -k "status" -v
```

Expected: FAIL — `status` command not registered

- [ ] **Step 3: Implement `status` command**

Add to `cli.py`:
```python
def _load_pipeline() -> manifest.Manifest:
    path = Path("pipeline.json")
    if not path.exists():
        click.echo("pipeline.json not found. Run 'artpipeline parse <brief>' first.", err=True)
        sys.exit(1)
    return manifest.load(path), path


@main.command()
@click.option("--asset", default=None, help="Show a single asset by ID")
@click.pass_context
def status(ctx, asset):
    """Show pipeline status."""
    m, _ = _load_pipeline()
    human = ctx.obj["human"]

    if asset:
        try:
            a = m.get_asset(asset)
        except KeyError as e:
            click.echo(str(e), err=True)
            sys.exit(1)
        from dataclasses import asdict
        _emit(asdict(a), human)
        return

    grouped = {}
    for a in m.assets.values():
        grouped.setdefault(a.status, []).append({"id": a.id, "type": a.type})
    _emit(grouped, human)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_cli.py -k "status" -v
```

Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add artpipeline/cli.py tests/test_cli.py
git commit -m "feat: add status command"
```

---

## Task 7: `next` Command

**Files:**
- Modify: `artpipeline/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_cli.py`:
```python
def test_next_returns_first_pending(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    result = runner.invoke(main, ["next"], catch_exceptions=False)
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["asset_id"] == "bird_crane_1x"
    assert "artpipeline prompt bird_crane_1x" in output["next_command"]


def test_next_with_stage_filter(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    result = runner.invoke(main, ["next", "--stage", "prompted"], catch_exceptions=False)
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["asset_id"] is None


def test_next_all_approved(runner, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    import json as _json
    from tests.conftest import SAMPLE_MANIFEST_DATA
    import copy
    data = copy.deepcopy(SAMPLE_MANIFEST_DATA)
    data["assets"]["bird_crane_1x"]["status"] = "approved"
    (tmp_project / "pipeline.json").write_text(_json.dumps(data, indent=2))
    result = runner.invoke(main, ["next"], catch_exceptions=False)
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["asset_id"] is None
    assert output["message"] == "All assets approved."
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_cli.py -k "next" -v
```

Expected: FAIL — `next` command not registered

- [ ] **Step 3: Implement `next` command**

Add to `cli.py`:
```python
_NEXT_COMMANDS = {
    "pending": "artpipeline prompt {id}",
    "prompted": "artpipeline file <downloaded-image> {id}",
    "filed": "artpipeline review {id}",
    "rejected": "artpipeline prompt {id} --retry",
}


@main.command(name="next")
@click.option("--stage", default=None,
              type=click.Choice(["pending", "prompted", "filed", "approved", "rejected"]),
              help="Filter to assets at a specific status")
@click.pass_context
def next_cmd(ctx, stage):
    """Return the next asset needing action."""
    m, _ = _load_pipeline()

    for a in m.assets.values():
        if stage:
            if a.status != stage:
                continue
        if a.status == "approved":
            continue
        cmd = _NEXT_COMMANDS.get(a.status, "artpipeline status --asset {id}").format(id=a.id)
        _emit({"asset_id": a.id, "status": a.status, "next_command": cmd}, ctx.obj["human"])
        return

    _emit({"asset_id": None, "message": "All assets approved."}, ctx.obj["human"])
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_cli.py -k "next" -v
```

Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add artpipeline/cli.py tests/test_cli.py
git commit -m "feat: add next command"
```

---

## Task 8: `prompt` Command

**Files:**
- Modify: `artpipeline/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_cli.py`:
```python
def test_prompt_returns_prompt(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    result = runner.invoke(main, ["prompt", "bird_crane_1x"], catch_exceptions=False)
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert "Sandhill Crane" in output["prompt"]
    assert output["retry_count"] == 0


def test_prompt_sets_status_prompted(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    runner.invoke(main, ["prompt", "bird_crane_1x"], catch_exceptions=False)
    import json as _json
    data = _json.loads((tmp_project / "pipeline.json").read_text())
    assert data["assets"]["bird_crane_1x"]["status"] == "prompted"


def test_prompt_retry_prepends_revision(runner, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    import json as _json, copy
    from tests.conftest import SAMPLE_MANIFEST_DATA
    data = copy.deepcopy(SAMPLE_MANIFEST_DATA)
    data["assets"]["bird_crane_1x"]["status"] = "rejected"
    data["assets"]["bird_crane_1x"]["rejection_reason"] = "neck not visible"
    (tmp_project / "pipeline.json").write_text(_json.dumps(data, indent=2))
    result = runner.invoke(main, ["prompt", "bird_crane_1x", "--retry"], catch_exceptions=False)
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert "neck not visible" in output["prompt"]
    assert "REVISION" in output["prompt"]


def test_prompt_unknown_asset_fails(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    result = runner.invoke(main, ["prompt", "nonexistent"])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_cli.py -k "prompt" -v
```

Expected: FAIL — `prompt` command not registered

- [ ] **Step 3: Implement `prompt` command**

Add to `cli.py`:
```python
@main.command()
@click.argument("asset_id")
@click.option("--retry", is_flag=True, help="Generate revised prompt using stored rejection reason")
@click.pass_context
def prompt(ctx, asset_id, retry):
    """Get the image-gen prompt for an asset."""
    m, pipeline_path = _load_pipeline()
    try:
        a = m.get_asset(asset_id)
    except KeyError as e:
        click.echo(str(e), err=True)
        sys.exit(1)

    text = a.prompt
    if retry:
        reason = a.rejection_reason or "no reason recorded"
        text = (
            f"REVISION REQUEST: The previous attempt was rejected because: \"{reason}\".\n"
            f"Please adjust accordingly.\n\n{text}"
        )

    a.status = "prompted"
    manifest.save(m, pipeline_path)

    _emit({"asset_id": a.id, "prompt": text, "retry_count": a.retry_count}, ctx.obj["human"])
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_cli.py -k "prompt" -v
```

Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add artpipeline/cli.py tests/test_cli.py
git commit -m "feat: add prompt command"
```

---

## Task 9: `file` Command

**Files:**
- Modify: `artpipeline/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_cli.py`:
```python
def test_file_copies_image(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    src = tmp_project / "downloaded.png"
    src.write_bytes(b"fake png data")
    result = runner.invoke(main, ["file", str(src), "bird_crane_1x"], catch_exceptions=False)
    assert result.exit_code == 0
    dest = tmp_project / "art" / "birds" / "crane@1x.png"
    assert dest.exists()
    assert dest.read_bytes() == b"fake png data"


def test_file_sets_status_filed(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    src = tmp_project / "downloaded.png"
    src.write_bytes(b"fake")
    runner.invoke(main, ["file", str(src), "bird_crane_1x"], catch_exceptions=False)
    import json as _json
    data = _json.loads((tmp_project / "pipeline.json").read_text())
    assert data["assets"]["bird_crane_1x"]["status"] == "filed"
    assert data["assets"]["bird_crane_1x"]["filed_path"] is not None


def test_file_missing_source_fails(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    result = runner.invoke(main, ["file", str(tmp_project / "missing.png"), "bird_crane_1x"])
    assert result.exit_code != 0


def test_file_wrong_extension_fails(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    src = tmp_project / "image.jpg"
    src.write_bytes(b"fake")
    result = runner.invoke(main, ["file", str(src), "bird_crane_1x"])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_cli.py -k "file" -v
```

Expected: FAIL — `file` command not registered

- [ ] **Step 3: Implement `file` command**

Add to `cli.py`:
```python
import shutil

_EXPECTED_EXTENSIONS = {
    "bird_sprite": ".png",
    "app_icon": ".png",
    "ui_glyph": ".svg",
}


@main.command(name="file")
@click.argument("image_path", type=click.Path(path_type=Path))
@click.argument("asset_id")
@click.pass_context
def file_cmd(ctx, image_path, asset_id):
    """Copy a downloaded image to its pipeline destination."""
    m, pipeline_path = _load_pipeline()

    if not image_path.exists():
        click.echo(f"Source file not found: {image_path}", err=True)
        sys.exit(1)

    try:
        a = m.get_asset(asset_id)
    except KeyError as e:
        click.echo(str(e), err=True)
        sys.exit(1)

    expected_ext = _EXPECTED_EXTENSIONS.get(a.type, ".png")
    if image_path.suffix.lower() != expected_ext:
        click.echo(
            f"Wrong file extension '{image_path.suffix}' for asset type '{a.type}'. "
            f"Expected '{expected_ext}'.",
            err=True,
        )
        sys.exit(1)

    dest = pipeline_path.parent / a.destination
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(image_path, dest)

    a.filed_path = str(a.destination)
    a.status = "filed"
    manifest.save(m, pipeline_path)

    _emit({"asset_id": a.id, "filed_path": a.filed_path}, ctx.obj["human"])
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_cli.py -k "file" -v
```

Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add artpipeline/cli.py tests/test_cli.py
git commit -m "feat: add file command"
```

---

## Task 10: `review` Command

**Files:**
- Modify: `artpipeline/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_cli.py`:
```python
def test_review_outputs_checks_and_criteria(runner, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    import json as _json, copy, shutil
    from tests.conftest import SAMPLE_MANIFEST_DATA
    data = copy.deepcopy(SAMPLE_MANIFEST_DATA)
    data["assets"]["bird_crane_1x"]["status"] = "filed"
    # Place a real PNG so the file_exists check passes
    art_dir = tmp_project / "art" / "birds"
    art_dir.mkdir(parents=True)
    dest = art_dir / "crane@1x.png"
    dest.write_bytes(b"fake")
    data["assets"]["bird_crane_1x"]["filed_path"] = "art/birds/crane@1x.png"
    (tmp_project / "pipeline.json").write_text(_json.dumps(data, indent=2))

    result = runner.invoke(main, ["review", "bird_crane_1x"], catch_exceptions=False)
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert "checks" in output
    assert output["checks"]["file_exists"] is True
    assert "acceptance_criteria" in output
    assert len(output["acceptance_criteria"]) == 2
    assert output["visual_review_required"] is True


def test_review_unfiled_asset_fails(runner, pipeline_file, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    result = runner.invoke(main, ["review", "bird_crane_1x"])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_cli.py -k "review" -v
```

Expected: FAIL — `review` command not registered

- [ ] **Step 3: Implement `review` command**

Add to `cli.py`:
```python
from artpipeline import review as review_mod


@main.command()
@click.argument("asset_id")
@click.pass_context
def review(ctx, asset_id):
    """Run programmatic checks and surface acceptance criteria."""
    m, pipeline_path = _load_pipeline()
    try:
        a = m.get_asset(asset_id)
    except KeyError as e:
        click.echo(str(e), err=True)
        sys.exit(1)

    if a.status not in ("filed", "approved", "rejected"):
        click.echo(
            f"Asset '{asset_id}' has status '{a.status}' — it must be filed before review. "
            "Run 'artpipeline file <image> {asset_id}' first.",
            err=True,
        )
        sys.exit(1)

    filed_path = pipeline_path.parent / a.destination
    checks = review_mod.run_checks(filed_path, a.dimensions)

    _emit(
        {
            "asset_id": a.id,
            "checks": checks,
            "acceptance_criteria": a.acceptance_criteria,
            "visual_review_required": True,
        },
        ctx.obj["human"],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_cli.py -k "review" -v
```

Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add artpipeline/cli.py tests/test_cli.py
git commit -m "feat: add review command"
```

---

## Task 11: `approve` and `reject` Commands

**Files:**
- Modify: `artpipeline/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_cli.py`:
```python
def _make_filed_pipeline(tmp_project):
    import json as _json, copy
    from tests.conftest import SAMPLE_MANIFEST_DATA
    data = copy.deepcopy(SAMPLE_MANIFEST_DATA)
    data["assets"]["bird_crane_1x"]["status"] = "filed"
    (tmp_project / "pipeline.json").write_text(_json.dumps(data, indent=2))


def test_approve_sets_status(runner, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    _make_filed_pipeline(tmp_project)
    result = runner.invoke(main, ["approve", "bird_crane_1x"], catch_exceptions=False)
    assert result.exit_code == 0
    import json as _json
    data = _json.loads((tmp_project / "pipeline.json").read_text())
    assert data["assets"]["bird_crane_1x"]["status"] == "approved"


def test_reject_sets_status_and_reason(runner, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    _make_filed_pipeline(tmp_project)
    result = runner.invoke(
        main, ["reject", "bird_crane_1x", "--reason", "neck not visible"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    import json as _json
    data = _json.loads((tmp_project / "pipeline.json").read_text())
    assert data["assets"]["bird_crane_1x"]["status"] == "rejected"
    assert data["assets"]["bird_crane_1x"]["rejection_reason"] == "neck not visible"
    assert data["assets"]["bird_crane_1x"]["retry_count"] == 1


def test_reject_without_reason_fails(runner, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    _make_filed_pipeline(tmp_project)
    result = runner.invoke(main, ["reject", "bird_crane_1x"])
    assert result.exit_code != 0


def test_reject_then_prompt_retry_transitions(runner, tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    _make_filed_pipeline(tmp_project)
    runner.invoke(main, ["reject", "bird_crane_1x", "--reason", "neck not visible"],
                  catch_exceptions=False)
    result = runner.invoke(main, ["prompt", "bird_crane_1x", "--retry"], catch_exceptions=False)
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert "neck not visible" in output["prompt"]
    import json as _json
    data = _json.loads((tmp_project / "pipeline.json").read_text())
    assert data["assets"]["bird_crane_1x"]["status"] == "prompted"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_cli.py -k "approve or reject" -v
```

Expected: FAIL — commands not registered

- [ ] **Step 3: Implement `approve` and `reject` commands**

Add to `cli.py`:
```python
@main.command()
@click.argument("asset_id")
@click.pass_context
def approve(ctx, asset_id):
    """Mark an asset as approved."""
    m, pipeline_path = _load_pipeline()
    try:
        a = m.get_asset(asset_id)
    except KeyError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    a.status = "approved"
    manifest.save(m, pipeline_path)
    _emit({"asset_id": a.id, "status": a.status}, ctx.obj["human"])


@main.command()
@click.argument("asset_id")
@click.option("--reason", required=True, help="Why the asset was rejected (used in retry prompt)")
@click.pass_context
def reject(ctx, asset_id, reason):
    """Mark an asset as rejected and store the reason for retry."""
    m, pipeline_path = _load_pipeline()
    try:
        a = m.get_asset(asset_id)
    except KeyError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    a.status = "rejected"
    a.rejection_reason = reason
    a.retry_count += 1
    manifest.save(m, pipeline_path)
    _emit({"asset_id": a.id, "status": a.status, "retry_count": a.retry_count}, ctx.obj["human"])
```

- [ ] **Step 4: Run all tests**

```bash
pytest tests/ -v
```

Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add artpipeline/cli.py tests/test_cli.py
git commit -m "feat: add approve and reject commands"
```

---

## Task 12: Art-Director Skill Update

**Files:**
- Modify: `~/.claude/skills/art-director/SKILL.md`

- [ ] **Step 1: Read the skill's `Handoff-mode additions` section**

Open `~/.claude/skills/art-director/SKILL.md` and locate the bullet list under `### Handoff-mode additions`. It ends with:
```
- **Repository directory layout** — show the full target tree...
```

- [ ] **Step 2: Add the Asset Manifest instruction after "Repository directory layout"**

After the `- **Repository directory layout** ...` bullet and before `Deliver handoff briefs as a markdown file...`, insert:

```markdown
- **`## Asset Manifest` YAML block** — after all other sections, append a final `## Asset Manifest` section containing a fenced YAML block in the following schema. This block is parsed by the `artpipeline` CLI tool; every asset listed in the inventory table must have a corresponding entry here.

  ```yaml
  project: <project name>
  direction: <direction codename>
  assets:
    - id: <asset_id>           # snake_case: bird_crane_1x, ui_rotate, icon_master
      type: <type>             # bird_sprite | ui_glyph | app_icon
      destination: <path>      # relative path from project root: art/birds/crane@1x.png
      dimensions: [w, h]       # expected pixel dimensions as integers
      prompt: "<full image-gen prompt for this asset>"
      acceptance_criteria:
        - "<criterion 1>"
        - "<criterion 2>"
      # bird_sprite only — include these fields:
      species: <species>       # crane | snowgoose | mallard | pintail | swan
      resolution: <res>        # 1x | 2x | 3x
  ```

  Rules for the YAML block:
  - Every `id` must be unique within the manifest.
  - For bird sprites with multiple resolutions, create one entry per resolution (e.g. `bird_crane_1x`, `bird_crane_2x`, `bird_crane_3x`).
  - The `prompt` field must be the complete ready-to-use image-gen prompt for that specific asset — not a reference to another section.
  - The `acceptance_criteria` list must be specific and testable, not vague ("must be a recognisable silhouette at 16×16 px" not "looks good").
```

- [ ] **Step 3: Verify the skill file is valid Markdown (scan for unclosed fences)**

Open the file and visually confirm the fenced block is correctly closed and the heading hierarchy is unchanged.

- [ ] **Step 4: Commit the skill update**

```bash
git add ~/.claude/skills/art-director/SKILL.md
git commit -m "feat: add Asset Manifest YAML block instruction to art-director skill"
```

Note: this commits to the `c.artpipelinetool` repo for record, but the actual skill file lives at the path above and takes effect immediately for the next art-director invocation.

---

## Final Smoke Test

- [ ] **Run the full test suite**

```bash
pytest tests/ -v
```

Expected: All PASSED

- [ ] **End-to-end manual check**

With the Matador brief from Google Drive saved locally as `matador-brief.md` (after adding an `## Asset Manifest` block via the updated art-director skill), verify:

```bash
artpipeline parse matador-brief.md
artpipeline status
artpipeline next
artpipeline prompt bird_crane_1x
artpipeline --help
```

All commands should return valid JSON with exit code 0.
