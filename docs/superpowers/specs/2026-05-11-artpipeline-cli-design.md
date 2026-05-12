# artpipeline CLI — Design Spec

**Date**: 2026-05-11
**Status**: Draft — awaiting human sign-off
**Project**: c.artpipelinetool

---

## Overview

`artpipeline` is a Python CLI tool used by Claude Cowork (an AI agent with browser access via a web extension) to drive an art asset production pipeline for casual mobile games. The agent reads an art brief produced by the `art-director` skill, generates image assets via OpenAI's web image generator, and files/reviews/iterates on each asset until it meets the brief's acceptance criteria.

The tool does **not** interact with the browser — Claude Cowork handles all browser operations itself. The tool handles everything else: parsing the brief, serving prompts, filing images, running checks, and tracking pipeline state.

---

## Scope

### In scope
- Parsing art briefs into a structured asset manifest
- Serving image-gen prompts (initial and retry with revision context)
- Filing downloaded images to their correct destination paths
- Running programmatic review checks (dimensions, format, transparency)
- Surfacing acceptance criteria as a checklist for Claude Cowork's visual review
- Tracking per-asset status across a full pipeline run
- Supporting iteration on individual assets via reject/retry cycle

### Out of scope
- Browser automation or any OpenAI API calls
- Audio asset production
- Code asset generation (shaders, Godot scenes)
- Image editing or post-processing

---

## Architecture

### Stack
- **Language**: Python 3.10+
- **CLI framework**: Click
- **Dependencies**: stdlib only beyond Click (no image-processing libraries — file checks use Pillow only for dimension/alpha reads, treated as an optional dependency with graceful fallback)
- **Platform**: Cross-platform (Windows + macOS)

### Central artifact: `pipeline.json`
A manifest file created by `parse` and updated by every subsequent command. Lives in the same directory as the brief. Tracks every asset from initial prompt through final approval.

### Output contract
- All commands write JSON to **stdout**
- Errors write to **stderr** with a non-zero exit code
- A `--human` flag on any command switches to human-readable output (for development use)

---

## The `pipeline.json` Schema

```json
{
  "brief": "matador-brief.md",
  "project": "Matador",
  "direction": "Murmuration",
  "assets": {
    "bird_crane_1x": {
      "status": "pending",
      "type": "bird_sprite",
      "species": "crane",
      "resolution": "1x",
      "destination": "art/birds/crane@1x.png",
      "dimensions": [48, 48],
      "prompt": "Top-down silhouette of a Sandhill Crane...",
      "acceptance_criteria": [
        "Silhouette only, no internal detail",
        "Transparent background, no halo, no anti-alias contamination",
        "Bird oriented facing up (north)",
        "Long neck clearly visible at 1x scale",
        "Distinguishable from all other species at 16x16 effective size"
      ],
      "rejection_reason": null,
      "retry_count": 0,
      "filed_path": null
    }
  }
}
```

### Asset ID conventions
Derived deterministically from the brief's asset manifest block:

| Asset type    | ID pattern                        | Example            |
|---------------|-----------------------------------|--------------------|
| Bird sprite   | `bird_<species>_<resolution>`     | `bird_crane_1x`    |
| UI glyph      | `ui_<name>`                       | `ui_rotate`        |
| App icon      | `icon_<variant>`                  | `icon_master`, `icon_60x60` |

### Status lifecycle
```
pending → prompted → filed → approved
                  ↘         ↗
                   rejected  (retry_count++)
```
A rejected asset returns to `prompted` status, ready for `prompt --retry`.

---

## Subcommand Reference

### `parse <brief.md>`
Creates or refreshes `pipeline.json` from the brief's `## Asset Manifest` YAML block (see Brief Format section). Safe to re-run — preserves existing asset statuses and adds any new assets. Writes `pipeline.json` alongside the brief.

**Output**: JSON list of all assets with their initial status.

**Error**: exits non-zero with a clear message if the `## Asset Manifest` block is absent.

---

### `status [--asset <id>]`
Prints all assets grouped by status. With `--asset`, prints the full record for one asset.

---

### `next [--stage <prompted|filed|reviewed>]`
Returns the single next asset needing action, in the order assets appear in the brief. Includes the recommended next command to run.

**Output example**:
```json
{
  "asset_id": "bird_crane_1x",
  "status": "pending",
  "next_command": "artpipeline prompt bird_crane_1x"
}
```

With `--stage <status>`, filters to assets at a specific status (`pending`, `prompted`, `filed`, `approved`, `rejected`). Useful if Claude Cowork is batching operations of the same type.

---

### `prompt <asset-id> [--retry]`
Returns the image-gen prompt for the asset. Updates status to `prompted`.

Updates status to `prompted` regardless of prior status — this is the correct transition from both `pending` and `rejected`.

Without `--retry`: returns the prompt verbatim from the manifest.

With `--retry`: prepends a revision instruction to the prompt:
```
REVISION REQUEST: The previous attempt was rejected because: "<rejection_reason>".
Please adjust accordingly.

[original prompt follows]
```

**Output**:
```json
{
  "asset_id": "bird_crane_1x",
  "prompt": "...",
  "retry_count": 0
}
```

---

### `file <image-path> <asset-id>`
Copies the image at `<image-path>` to the asset's `destination` path (relative to `pipeline.json`'s directory). Creates intermediate directories as needed. Updates `filed_path` and status to `filed`.

**Validation**: checks the source file exists and has the expected extension (PNG for sprites/icons, SVG for glyphs). Exits non-zero if either check fails.

**Output**:
```json
{
  "asset_id": "bird_crane_1x",
  "filed_path": "art/birds/crane@1x.png"
}
```

---

### `review <asset-id>`
Runs programmatic checks on the filed image, then prints the full acceptance criteria checklist for Claude Cowork's visual assessment.

**Programmatic checks** (requires Pillow; skipped gracefully if not installed):
- File exists at `filed_path`
- Dimensions match expected (e.g. 48×48 for a 1x bird sprite)
- PNG has an alpha channel (transparency present)

**Output**:
```json
{
  "asset_id": "bird_crane_1x",
  "checks": {
    "file_exists": true,
    "dimensions_correct": true,
    "has_alpha": true
  },
  "acceptance_criteria": [
    "Silhouette only, no internal detail",
    "Transparent background, no halo, no anti-alias contamination",
    "Bird oriented facing up (north)",
    "Long neck clearly visible at 1x scale",
    "Distinguishable from all other species at 16x16 effective size"
  ],
  "visual_review_required": true
}
```

---

### `approve <asset-id>`
Sets status to `approved`.

**Output**: `{"asset_id": "bird_crane_1x", "status": "approved"}`

---

### `reject <asset-id> --reason "<text>"`
Sets status to `rejected`, stores `rejection_reason`, increments `retry_count`. The asset is now ready for `prompt --retry`.

**Output**: `{"asset_id": "bird_crane_1x", "status": "rejected", "retry_count": 1}`

---

## Brief Format: The `## Asset Manifest` Block

The `art-director` skill will be updated to emit a structured YAML block at the end of every brief, under the heading `## Asset Manifest`. This is the sole input to `parse` — the prose sections of the brief are for human/art-director consumption only.

### Required fields per asset entry
```yaml
assets:
  - id: bird_crane_1x
    type: bird_sprite          # bird_sprite | ui_glyph | app_icon
    species: crane             # bird_sprite only
    resolution: 1x             # bird_sprite only: 1x | 2x | 3x
    destination: art/birds/crane@1x.png
    dimensions: [48, 48]       # expected pixel dimensions
    prompt: "Top-down silhouette of a Sandhill Crane..."
    acceptance_criteria:
      - "Silhouette only, no internal detail"
      - "Transparent background, no halo"
      - "Bird oriented facing up (north)"
      - "Long neck clearly visible at 1x scale"
      - "Distinguishable from all other species at 16x16 effective size"
```

### Top-level fields
```yaml
project: Matador
direction: Murmuration
assets:
  - ...
```

The `art-director` skill update is part of this project's implementation scope.

---

## Project Directory Layout

```
<project-root>/
├── <brief>.md              # the art brief
├── pipeline.json           # created by parse, updated by all commands
└── art/
    ├── birds/
    │   ├── crane@1x.png
    │   ├── crane@2x.png
    │   └── ...
    ├── ui/
    │   ├── rotate.svg
    │   └── ...
    └── icon/
        └── app_icon.png
```

The `destination` paths in the manifest are relative to the directory containing `pipeline.json`.

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| `## Asset Manifest` block missing from brief | `parse` exits 1 with message pointing to missing section |
| Asset ID not found in manifest | All commands exit 1 with list of valid IDs |
| Source file not found in `file` command | exits 1 |
| Wrong file extension in `file` command | exits 1 with expected extension |
| Pillow not installed for `review` | programmatic checks skipped, criteria checklist still printed, warning on stderr |
| `reject` called without `--reason` | exits 1 (reason is required for retry prompt quality) |

---

## Typical Full Pipeline Run

```
# Setup
artpipeline parse matador-brief.md

# Per-asset loop (Claude Cowork calls next, then works the asset)
artpipeline next
# → {"asset_id": "bird_crane_1x", "next_command": "artpipeline prompt bird_crane_1x"}

artpipeline prompt bird_crane_1x
# → Claude uses browser to generate image, downloads to ~/Downloads/img.png

artpipeline file ~/Downloads/img.png bird_crane_1x
artpipeline review bird_crane_1x
# → Claude Cowork visually checks criteria

artpipeline approve bird_crane_1x   # OR:
artpipeline reject bird_crane_1x --reason "neck not visible at 1x scale"
  artpipeline prompt bird_crane_1x --retry
  # → Claude regenerates, re-files, re-reviews
  artpipeline approve bird_crane_1x

artpipeline next
# → next asset...
```

---

## Implementation Notes

- `parse` should be idempotent and safe to re-run against an updated brief (e.g. if the art director revises the brief mid-production). New assets are added as `pending`; existing assets with status beyond `pending` are left untouched.
- Asset order in `pipeline.json` preserves the order from the brief's YAML block. `next` respects this order.
- The `--human` flag is intended for development/debugging only and should not be relied upon by Claude Cowork.
- All file paths in output JSON use forward slashes regardless of platform.

---

## Art-Director Skill Update

The `art-director` skill (`~/.claude/skills/art-director/SKILL.md`) will receive one addition: an instruction to emit an `## Asset Manifest` YAML block at the end of every brief, containing all deliverable assets in the schema described above. The human-readable Section 9 prose remains unchanged — the YAML block is an addition, not a replacement.
