# artpipeline v2 — Specification

Status: **draft v0.2 (decisions resolved)** · 2026-11-04 · branch `v2` · v1 preserved at tag `v0.1.0`

## 1. Purpose

Let an AI agent in Claude Code produce a full set of game art assets (tens to hundreds of files) that are correct, consistent, reviewable and reproducible, without the user babysitting each file.

v1 pursued the same goal, but its design assumed the agent drove an image generator through a browser. v2 assumes what agents can do today:

- They call generators and creative apps through MCP.
- They draw assets in code (SVG, shaders).
- They look at images directly.
- They fan work out to parallel subagents.

### Division of labour

| Owner | Responsibility |
|---|---|
| **`casual-mobile-art-director` skill** | Judgment: direction, style, routing an asset class to a tool, prompt writing, taste review, talking to the user. |
| **artpipeline v2 (this tool)** | Enforcement and memory: what exists, what state each asset is in, what was tried, what passed, what the user signed off, and where files go. Anything deterministic and repeatable. |
| **Connected tools** (image-gen MCPs, Recraft, VectorCraft, Canva, Blender, Claude-written SVG) | Producing pixels and vectors. **v2 never calls a generator itself.** |

### Non-goals (v2.0)

- Calling image-generation APIs or holding API keys. This may come later as optional providers.
- Running in claude.ai. Claude Code is the target; the CLI stays usable anywhere Python runs, but nothing is designed around the web sandbox.
- Art-direction logic. If a rule is about taste, it belongs in the skill.
- Migrating v1 `pipeline.json` files.

## 2. Principles

1. **State is enforced, not described.** Invalid transitions are refused with an actionable error, for example: approving an asset with no passing attempt, claiming a non-hero asset before the style is locked, or a fourth retry.
2. **Every attempt is kept.** Files, provenance (route, tool, model, prompt, seed, references), check results and decisions are append-only. The manifest is *generated* from that state; the model never hand-writes it.
3. **Judge at display size.** The review surface is a contact sheet at true in-game sizes on real backgrounds, returned as an image the model sees inline.
4. **Asset classes are data.** No hard-coded `bird_sprite`. Built-in presets cover common iOS/Godot/Phaser classes; briefs can define their own.
5. **Safe for parallel subagents.** Claims carry leases, and writes are transactional.
6. **Never clobber the user's work.** Placement into a project versions superseded files and requires explicit confirmation to overwrite. Read-only targets get a staging folder plus `INSTALL.md`.

## 3. Architecture

```
artpipeline/
  core/        schema (pydantic), store (SQLite), state machine, queue/leases, gates
  intake/      brief parsing (## Asset Manifest YAML, or standalone assets.yaml)
  imaging/     load/render (PNG, SVG via resvg-py), bg removal, trim, palette clamp,
               export renditions, checks, contact sheets   ← absorbs the skill's scripts
  placement/   targets: staging, xcassets, godot, phaser
  mcp/         FastMCP server — the primary interface
  cli/         JSON CLI mirroring the MCP tools (scripts, hooks, debugging, tests)
skills/casual-mobile-art-director/   the skill (moved here from its own repo; single source of truth)
.claude-plugin/  plugin.json + marketplace.json — the repo root is the plugin root
.mcp.json        launches `artpipeline mcp`
```

- **Python ≥3.11.** Dependencies: `mcp` (official Python SDK, 2.x), `pydantic`, `Pillow`, `PyYAML`, `resvg-py`.
- **SVG rendering goes through a renderer interface.**
  - The default is `resvg-py`, bundled and deterministic. It removes the skill's system-tool chain (rsvg-convert → Inkscape → cairosvg → Playwright). *To verify in M2: render fidelity on the skill's eval SVGs.*
  - **VectorCraft is optional.** `vectorcraft-cli export` can render instead when it is installed. Rendering in the same engine that authored the file avoids mismatches between the authoring and checking renderers.
  - Status on the author's machine (2026-11-04): `VectorCraft.app` 0.21.0 is installed, but `vectorcraft-cli` (headless and MCP) is not. `PhotoCraft.app` ships `photocraft-cli`, which has an `mcp` command.
  - The tool never depends on either app; they are authoring routes the skill picks.
- **One MCP server process per Claude Code session.** Subagents share it, and the CLI can run alongside it. SQLite in WAL mode makes concurrent writes safe either way.

### On-disk layout (inside the user's project, or a chosen output folder)

```
.artpipeline/
  pipeline.db              SQLite: assets, attempts, events, gates, locks
  attempts/<asset>/<n>/    source file as registered + processed outputs + renditions
  sheets/                  contact sheets, numbered
  style-lock/              approved hero refs, style block, palette file
art-manifest.json          generated; git-friendly snapshot of every asset and its approved attempt
```

`init` writes `.artpipeline/.gitignore` containing `*`, so attempt files stay out of git without editing the user's own `.gitignore`. `art-manifest.json` is meant to be committed.

## 4. Data model

### 4.1 Asset class (preset or brief-defined)

```yaml
classes:
  game_center_badge:            # presets ship for: ios_app_icon_layer, ios_app_icon_flat,
    format: png                 #   game_center_badge, store_screenshot, sprite, ui_icon_svg,
    master: [1024, 1024]        #   pixel_sprite, tile, key_art
    alpha: forbidden            # required | forbidden | any
    renditions: []              # e.g. [{suffix: "@2x", scale: 2}, {suffix: "@3x", scale: 3}] or explicit px
    display_sizes: [256, 64]    # contact-sheet sizes
    review_backgrounds: ["#F2F2F7", "#1C1C1E"]
    checks: {halo: true, palette_min_share: 0.9, min_contrast: 3.0, greyscale_read: true}
    processing: [trim?, remove_bg?, palette_clamp: hard|soft|off, flatten: "#hex"?]
    pixel_art: false            # nearest-neighbour only, integer scales, no smoothing
```

### 4.2 Asset

`id`, `class`, `subject` (the per-asset subject line), `acceptance_criteria[]`, `hero: bool`, `destination` (relative, per target), `group` (for batching and colour groups), `needs_human_finish: bool`, `overrides` (any class field), `status`.

### 4.3 Attempt

`n`, `asset_id`, `registered_at`, `by` (agent label), `route` (`code_native | agent_app | image_gen | human`), `tool`, `model`, `prompt`, `seed`, `references[]`, `change_from_previous` (required when n > 1), `source_path`, `processed_path`, `renditions{}`, `checks{pass, fail[], warn[], metrics}`, `decision` (`approved | rejected | superseded | null`), `decision_by` (`user | agent`), `reason`.

### 4.4 Project-level records

- **StyleLock:** version, style block text, palette, reference attempts, `approved_by: user`, timestamp.
- **Gate:** id, kind (`style_lock | batch | in_engine`), assets covered, sheet path, `passed_by`, notes.
- **Event:** an append-only log of every mutation. It is the audit trail and the source for `history`.

## 5. State machine

```
pending ──claim──▶ in_progress ──register──▶ checking ──fail──▶ in_progress  (attempt n+1, if budget left)
   ▲                    │                       │                     │
   │               lease expires                pass                  budget spent
   └────────────────────┘                       ▼                     ▼
                                          awaiting_review          flagged ──(user)──▶ in_progress / waived
                                           │          │
                                    reject (reason)   approve
                                           │          ▼
                                           ▼       approved ──place──▶ placed
                                   in_progress (n+1) or flagged
```

### Enforced rules

| Rule | Default | Error when violated |
|---|---|---|
| Non-hero assets can't be claimed until a StyleLock exists. With no heroes in the brief, claims are allowed up to the gate threshold, then need a StyleLock | on | `STYLE_NOT_LOCKED`: lists the heroes and their states |
| A StyleLock requires every hero to be approved, and the lock itself is set with `by: user` | — | `HEROES_NOT_APPROVED` |
| Max attempts per asset; exceeding it moves the asset to `flagged` | 3 | `RETRY_BUDGET_SPENT` |
| An attempt with n > 1 must state `change_from_previous` | — | `NO_CAUSE_CHANGE`: "change the cause, don't reroll" |
| Approval requires a passing attempt and that attempt on a contact sheet | — | `NOT_REVIEWED` |
| Claims pause once agent-approved assets since the last gate reach the threshold, until a batch gate is passed | 15 | `GATE_DUE`: returns the sheet to show the user |
| Leases expire, and the asset becomes claimable again. A plain claim never returns an agent's own live leases; naming the asset in `asset_ids` renews the lease | 30 min | `LEASED_BY_OTHER` |

`approved_by: user` works on the honour system: the tool can't verify who decided, but it records the claim and the skill must only set it after the user actually responds. That honour system is acceptable here because the threat model is drift, not deception.

## 6. MCP tool surface

All tools return structured output (an output schema). Review tools also return image content.

| Tool | Purpose |
|---|---|
| `init(brief_path \| manifest, output_root, target?)` | Create or refresh the pipeline. Idempotent: new assets are added, changed specs are reported, and progress is kept. |
| `status(asset_id?, group?)` | Counts by state and gate status; with `asset_id`, the full record including attempt history. |
| `claim(n=1, agent, group?)` | Lease up to n claimable assets. Each comes with its **work packet**: the style block, subject, acceptance criteria, palette, references, sizes, alpha rule, and earlier attempts with their reasons. |
| `register_attempt(asset_id, file, provenance, change_from_previous?)` | Copy in, process, export renditions and run checks. Returns the check results plus an inline preview at display sizes. |
| `review_sheet(asset_ids? \| pending_review? \| gate?)` | Build a contact sheet (true sizes, review backgrounds, greyscale row, labels with attempt numbers). Returns the image and its path, and marks those attempts as reviewed. |
| `decide(asset_id, decision, reason?, by)` | Approve or reject the current attempt. Rejecting requires a reason. |
| `lock_style(style_block, palette, hero_ids, by="user")` | Create a StyleLock version. Changing it later bumps the version and flags assets approved under the old lock for re-review. |
| `pass_gate(gate_id, by, notes?)` | Clear a batch or in-engine gate. |
| `flag` / `unflag(asset_id, reason)` | Hand an asset to the human, or take it back. |
| `place(asset_ids \| approved, target, confirm_overwrite=false)` | Write files into the engine layout (see §7). Returns the files written and anything superseded. |
| `export_manifest()` | Write `art-manifest.json`. Also runs automatically after every decision. |
| `handback()` | Summary: counts, final sheet, failures and flags, assets needing a human finish, and the 3–5 assets most likely to need taste revisions (ranked by attempts and warnings). |
| `process` / `check(file, class \| options)` | Stateless utilities for one-off use outside a pipeline. These replace the skill's scripts. |

The **CLI** mirrors the tools one to one (`artpipeline claim --n 4 --agent sub-2`, and so on), outputs JSON to stdout with errors to stderr, and uses the same error codes. `artpipeline mcp` starts the server.

## 7. Placement targets

| Target | Writes |
|---|---|
| `staging` (default; required for read-only repos) | `<output>/<destination>`, plus an `INSTALL.md` with exact copy steps |
| `xcassets` | `*.imageset/` and `*.appiconset/` with `Contents.json` (scales, idioms); Game Center art |
| `godot` | Files under `res://` paths, plus `.import` presets per class (filter off for pixel art) |
| `phaser` | Individual files plus a preload-manifest JSON entry; atlas packing through the TexturePacker CLI when present (M4) |

Before any write, existing files are moved to `superseded/` with a timestamp, unless `confirm_overwrite` is set. Every placed file is recorded in the manifest.

## 8. Packaging and install

- **PyPI package `artpipeline` 2.0.0** with console script `artpipeline`.
- **Claude Code plugin:** the repo root is the plugin. It contains `.claude-plugin/plugin.json`, a `marketplace.json` so users can `/plugin marketplace add mrjoshuahoward/artpipelinetool`, the skill, and an `.mcp.json` that launches `artpipeline mcp`. Optional hooks, for example running `export_manifest` on session stop.
- **The skill lives in this repo** at `skills/casual-mobile-art-director/` and ships inside the plugin.
  - The standalone `casual-mobile-art-director` repo will be archived, pointing here.
  - The May copy at `skills/art-director/` is deleted.
  - When the plugin is installed, remove the claude.ai-uploaded copy of the skill so two versions don't compete.

## 9. What changes from v1

| Removed | Why |
|---|---|
| The `prompt` → paste → download → `file` browser flow | Generation happens through connected tools; v2 registers the result. |
| White-background keying | Prefer native alpha, or a chroma-key background with real background removal and halo checks. |
| Hard-coded `bird_sprite` / `ui_glyph` / `app_icon`, and `species` | Replaced by data-defined classes. |
| `REVISION REQUEST` prompt prepending | The work packet carries prior attempts and reasons; the skill decides how to change the cause. |
| `AGENT.md` | Replaced by MCP tool descriptions plus the skill. Removes the hard-coded Windows path. |
| `pipeline.json` rewritten on every call | Replaced by SQLite plus the event log. |

## 10. Decisions (resolved 2026-11-04)

1. **The skill moves into this repo,** and the plugin is one repo. The standalone skill repo will be archived.
2. **Briefs without heroes are allowed with a warning.** `init` warns. Claims of non-hero assets stop at the gate threshold (15) until a `lock_style` exists.
3. **`.artpipeline/` is git-ignored by default.** Commit `art-manifest.json`.
4. **Python.**

## 11. Milestones

| M | Scope | Done when |
|---|---|---|
| **M1 Core** ✅ 2026-11-04 | Schema, store, state machine, leases, gates, intake, CLI | Unit tests cover every transition and error code; concurrent-claim test with 8 workers |
| **M2 Imaging** ✅ 2026-11-04 | Port and test the skill's checks, processing, exports and contact sheets; `resvg-py` rendering | Same verdicts as the skill's scripts on the eval assets. **Result:** check metrics (mean, palette share and worst ΔE, contrast) and pass/fail match the skill on the test fixtures, and Lanczos exports match pixel for pixel. Clamping differs on fewer than 2% of pixels (exact-colour cache instead of the skill's order-dependent bucketed cache). The skill's evals left no saved assets to compare, so parity was tested on fixtures. Deliberate departures: see §12 |
| **M3 MCP + plugin** ✅ 2026-11-04 (eval run pending) | MCP server (`mcp` 2.x `MCPServer`), structured outputs, inline images, plugin packaging; update the skill's `production-loop.md` to use the tool | Badges eval runs end to end in Claude Code through the plugin. **Done:** tools, in-process and stdio tests, `claude plugin validate`, and a headless Claude Code session using the plugin's tool. **Pending:** the badges eval itself (billed; run with the user's go-ahead) |
| **M4 Placement** | Staging, xcassets, godot, phaser | Sorting Line badges placed into a scratch copy and verified in the simulator |
| **M5 Eval and release** | Run the skill's evals with and without the tool; README; 2.0.0 tag | Pass rate ≥ skill alone; fewer manifest errors and gate violations; cost and time reported |

Evals reuse `casual-mobile-art-director/evals/` (Sorting Line, read-only). Additional measures: manifest accuracy, invalid-transition attempts caught, retries per asset, and wall-clock time with parallel subagents.

## 12. Imaging notes (M2)

**Where v2 deliberately differs from the skill's scripts:**

| Area | Skill scripts | v2 | Why |
|---|---|---|---|
| Halo check | Compares soft edge pixels with the asset's *global* mean colour | Compares each soft edge pixel with the solid pixels within 2 px | The global version fails healthy keylined art at small sizes. A 44 px light icon with a dark outline scores 87% "halo". The local version still fails real matte fringes (tested). |
| Greyscale read | Described, never computed | Warns when colours differ mostly in hue (hue spread > 25, lightness range < 10) | Catches red/green-at-equal-lightness art that vanishes in greyscale or for colour-blind players. Warn only. |
| Contact sheets | Squares every asset; Lanczos for everything; one size/background set per sheet | Keeps aspect; nearest-neighbour for pixel art; per-asset sizes and backgrounds; a background margin round every tile; pages of 12 | Screenshots were distorted, pixel art blurred, and opaque art could not be judged against the background at full size. |
| Palette clamp cache | Bucketed by 6-bit colour, first pixel seen wins | Exact colour | The skill's result depends on scan order. |
| SVG rendering | rsvg-convert → Inkscape → cairosvg → Playwright (none installed on the author's machine) | Bundled `resvg-py` | Works out of the box. |

**Processing order** (raster classes):
1. Load the source, or render an SVG source at the master size.
2. `remove_bg`: a chroma key connected to the border, so enclosed areas of the same colour survive.
3. `trim`.
4. Fit to the master: never upscale; aspect must match unless trimmed (then pad to fit); pixel art needs integer factors.
5. `flatten`.
6. `palette_clamp`. Flattening comes before clamping; the other order leaves anti-aliased edges off-palette.
7. Renditions: re-rendered from SVG when possible, otherwise downscaled.

A processing refusal, such as an upscale, is a check failure, so it feeds the retry loop.

**Still to do:**
- A VectorCraft render backend, blocked until `vectorcraft-cli` is installed and its export syntax verified.
- The skill's `scripts/` stay in place until M3 switches the skill to `artpipeline check / process / contact-sheet` and the MCP tools.

## 13. MCP and packaging notes (M3)

- **SDK:** `mcp` 2.x renamed `FastMCP` to `MCPServer`. Tools build `CallToolResult` directly: structured content, a text copy, and image blocks. Refusals are `is_error` results carrying the error code and hint. `by` parameters are typed: `Literal["user"]` for lock, gate and unflag; `"user" | "agent"` for decide and flag.
- **Images:**
  - The model sees one strip per asset, not the full page. Images with a long edge over 1,568 px are scaled down by the client, which would make tiles lie about size. Full pages are saved for the user.
  - `register_attempt` returns the asset's strip by default, and that counts as review.
  - `claim` shows up to 4 locked reference images as 384 px thumbnails.
- **Finding the pipeline:**
  1. the session's `init` / `open_pipeline`;
  2. otherwise `ARTPIPELINE_ROOT`;
  3. otherwise `CLAUDE_PROJECT_DIR`, searching up and up to two levels down (refused if ambiguous).
- **Packaging:**
  - The repo root is the plugin and its own marketplace (`"source": "./"`).
  - `.mcp.json` launches `bin/artpipeline-mcp`. That script runs `bin/artpipeline-bootstrap`, which builds a venv in `${CLAUDE_PLUGIN_DATA}` (persistent across updates) and rebuilds when the plugin path or source hash changes. Concurrent setup is serialised with a lock folder.
  - A `SessionStart` hook warms the same venv. The docs don't say whether hooks finish before MCP servers start, so both paths exist.
  - Nothing ever writes to stdout.
  - Measured: first setup 5.9 s with a warm pip cache, then 19 ms.
- **The skill's scripts** moved to `tests/reference/skill_scripts/`, kept only for the parity tests.
