# artpipeline

A Python CLI tool that gives an AI agent the operational backbone it needs to run an art asset production pipeline for casual mobile games — parsing briefs, serving prompts, filing images, and tracking per-asset status through review and approval.

---

## What this is

Generating a game art asset with an AI image tool is easy. Generating 40 assets systematically — with correct filenames, correct dimensions, transparent backgrounds, and the ability to reject and retry individual assets with context about what went wrong — requires structure the image tool doesn't provide.

`artpipeline` is that structure. It handles everything except the browser:

- Parsing a structured art brief into a trackable asset manifest
- Serving the image-gen prompt for each asset (including revision prompts that carry rejection context forward)
- Filing downloaded images to their correct destination paths
- Running programmatic checks (dimensions, alpha channel) and surfacing acceptance criteria
- Tracking each asset through its full lifecycle: `pending → prompted → filed → approved`

The AI agent handles everything in the browser: submitting prompts to the image generator, reviewing generated images visually, downloading results.

---

## System overview

This repo contains two components designed to work together:

```
┌─────────────────────────────────────────────────────────────┐
│  You (Claude Code + art-director skill)                      │
│                                                              │
│  /art-director  →  produces a handoff brief (.md)           │
│                    with structured ## Asset Manifest YAML    │
└────────────────────────┬────────────────────────────────────┘
                         │ brief.md
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  AI agent with browser access ("Claude Cowork")             │
│                                                              │
│  artpipeline parse brief.md      → creates pipeline.json   │
│                                                              │
│  loop:                                                       │
│    artpipeline next              → which asset to do next   │
│    artpipeline prompt <id>       → gets the prompt text     │
│    [ pastes prompt → OpenAI image generator in browser ]    │
│    [ downloads generated image ]                            │
│    artpipeline file <img> <id>   → files it correctly       │
│    artpipeline review <id>       → checks + criteria        │
│    [ visually inspects ]                                     │
│    artpipeline approve <id>      → done                     │
│    artpipeline reject <id> \                                 │
│      --reason "neck not visible" → retry with context       │
└─────────────────────────────────────────────────────────────┘
```

### The two components

**`artpipeline` CLI** — the Python tool in this repo. Installed once; used by the AI agent during production runs.

**`art-director` skill** (`skills/art-director/SKILL.md`) — a [Claude Code skill](https://docs.anthropic.com/en/docs/claude-code/skills) that acts as a senior art director for casual mobile games. It produces the handoff brief that starts each production run. The skill knows to emit a structured `## Asset Manifest` YAML block at the end of every brief — the sole input to `artpipeline parse`.

---

## Requirements

- Python 3.10+
- [Claude Code](https://claude.ai/code) (for the art-director skill)
- An AI agent with browser access (for running the pipeline loop)
- `Pillow` (optional — enables dimension and alpha channel checks during review)

---

## Installation

### CLI tool

```bash
pip install -e ".[review]"   # with Pillow for image checks (recommended)
# or
pip install -e .             # without image checks
```

### art-director skill

Copy the skill into your Claude Code skills directory:

```bash
# macOS / Linux
cp -r skills/art-director ~/.claude/skills/

# Windows
xcopy /E skills\art-director %USERPROFILE%\.claude\skills\art-director\
```

The skill is then available in Claude Code as `/art-director`.

> **Note:** The skill references supplementary files (`references/casual-mobile-canon.md`, etc.) that are not included in this repo — they are part of a larger personal workflow. The skill works fully without them.

---

## Workflow

### Step 1 — Produce a brief

In Claude Code, run `/art-director` and describe your game. Ask for a handoff brief. The skill will produce a Markdown file ending with an `## Asset Manifest` YAML block listing every asset to produce, with its prompt, expected dimensions, and acceptance criteria.

### Step 2 — Parse the brief

```bash
artpipeline parse my-game-brief.md
```

Creates `pipeline.json` alongside the brief. Safe to re-run — existing asset statuses are preserved.

### Step 3 — Run the production loop

Hand the brief and the `artpipeline` tool to your AI agent. The loop:

```bash
artpipeline next
# → {"asset_id": "bird_crane_1x", "next_command": "artpipeline prompt bird_crane_1x"}

artpipeline prompt bird_crane_1x
# → returns the full image-gen prompt; updates status to "prompted"

# [ agent submits prompt to image generator, downloads result ]

artpipeline file ~/Downloads/image.png bird_crane_1x
# → copies to art/birds/crane@1x.png; updates status to "filed"

artpipeline review bird_crane_1x
# → runs dimension/alpha checks; surfaces acceptance criteria for visual review

artpipeline approve bird_crane_1x
# → status: approved

# — or if it doesn't pass —

artpipeline reject bird_crane_1x --reason "neck not visible at 1x scale"
artpipeline prompt bird_crane_1x --retry
# → prompt now opens with "REVISION REQUEST: The previous attempt was rejected because..."
```

---

## Command reference

| Command | Description |
|---|---|
| `artpipeline parse <brief.md>` | Create or refresh `pipeline.json` from the brief |
| `artpipeline status [--asset <id>]` | Show all assets grouped by status, or one asset in full |
| `artpipeline next [--stage <status>]` | Return the next asset needing action |
| `artpipeline prompt <id> [--retry]` | Get the image-gen prompt; prepend revision context with `--retry` |
| `artpipeline file <img> <id>` | File a downloaded image to its destination path |
| `artpipeline review <id>` | Run programmatic checks and surface acceptance criteria |
| `artpipeline approve <id>` | Mark asset approved |
| `artpipeline reject <id> --reason "..."` | Mark asset rejected; store reason for retry |

All commands output JSON to stdout. Add `--human` for readable indented output during development.

---

## The `pipeline.json` state file

Every command reads and updates `pipeline.json`, which lives alongside the brief:

```json
{
  "brief": "my-game-brief.md",
  "project": "Matador",
  "direction": "Murmuration",
  "assets": {
    "bird_crane_1x": {
      "status": "filed",
      "type": "bird_sprite",
      "species": "crane",
      "resolution": "1x",
      "destination": "art/birds/crane@1x.png",
      "dimensions": [48, 48],
      "prompt": "Top-down silhouette of a Sandhill Crane...",
      "acceptance_criteria": [
        "Silhouette only, no internal detail",
        "Transparent background, no halo",
        "Bird oriented facing up (north)"
      ],
      "rejection_reason": null,
      "retry_count": 0,
      "filed_path": "art/birds/crane@1x.png"
    }
  }
}
```

Asset status lifecycle:

```
pending → prompted → filed → approved
                  ↘         ↗
                   rejected   (retry_count++)
```

---

## Project structure

```
artpipeline/
├── artpipeline/
│   ├── cli.py          # Click commands
│   ├── manifest.py     # pipeline.json schema, load/save
│   ├── parser.py       # ## Asset Manifest YAML extraction
│   └── review.py       # Programmatic image checks
├── tests/              # pytest suite (43 tests)
├── skills/
│   └── art-director/
│       └── SKILL.md    # Claude Code skill for producing art briefs
├── docs/
│   └── superpowers/
│       ├── specs/      # Design specification
│       └── plans/      # Implementation plan
└── pyproject.toml
```

---

## License

MIT — see [LICENSE](LICENSE).
