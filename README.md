# artpipeline

> **This is 2.1 (Nov 2026):** artpipeline now builds assets itself from committed recipes. 2.0 is at tag [`v2.0.0`](../../tree/v2.0.0) and the original v1 (May 2026, a browser-driven CLI) at [`v0.1.0`](../../tree/v0.1.0).

A Claude Code plugin that lets an agent produce a full set of casual-mobile game art (icons, sprites, badges, UI, store art) that is correct, consistent, reviewable and reproducible. It pairs:

- **the `casual-mobile-art-director` skill:** art direction, tool routing and taste review. Invoke it as `/artpipeline:casual-mobile-art-director`, or just ask for art direction or assets.
- **the `artpipeline` MCP server:** an enforced production pipeline.
  - Per-asset state.
  - Attempt history with provenance.
  - A user-signed style lock and batch review gates.
  - Retry budgets.
  - Automatic processing (background removal, fit, flatten, palette clamp, renditions) and checks (size, alpha, halo, palette, contrast, greyscale read).
  - Contact sheets shown to the model at true display sizes.
  - A generated `art-manifest.json`.

Assets reach the pipeline in two ways:
- **artpipeline builds them from recipes (new in 2.1).** Everything runs locally, with no network.
- **The agent produces them with whatever fits:** connected generators, VectorCraft/PhotoCraft, Canva, Blender. artpipeline doesn't call AI image generators itself; that may come later. 

Either way, artpipeline records, processes, checks and gates the result.

## Building from recipes

A brief asset with a `build:` entry is made by artpipeline from files committed with your project. One `build(group=...)` call claims, compiles, registers and checks a whole set.

| Kind | Makes | How |
|---|---|---|
| `svg` | Badges, UI icons, flat sprites, tiles | SVG templates with `<ap:slot/>` for the per-asset part, `{{tokens.gold}}` colours from the style, and shapes (`<ap:star>`, `<ap:gear>`, `<ap:ring>`, `<ap:burst>` and more) |
| `compose` | Store screenshots, key art, layered icons | A layer stack: backgrounds, images, other approved assets and captions, with fit, rounded clips, opacity, rotation and drop shadows |
| `derive` | Sprite sheets and texture atlases | Packs approved frames into a grid or packed atlas, with padding, edge extrusion and animation |
| `script` | Anything the others can't express | Runs a committed script that sees only the files it declares |

Text is drawn from a committed font as outlines (`<ap:text>` or compose text layers), so built files never depend on the viewer's fonts. Long titles can wrap or shrink to fit.

```yaml
style:
  tokens: {gold: "#F2C14E", ink: "#23282B"}
groups:
  badges: {build: {template: art-src/badge-frame.svg}}
assets:
  - {id: first-bloom, class: game_center_badge, subject: A first flower, group: badges,
     acceptance_criteria: [Reads at 64 px], destination: badges/first-bloom.png,
     build: {source: art-src/badges/first-bloom.svg, params: {label: "First Bloom"}}}
```

Builds are deterministic, so artpipeline knows when a recipe, template, font, param or token change makes an asset **stale**. Change a colour in the style lock and `build(stale=true)` rebuilds exactly the affected assets, plus, once those are re-approved, the screenshots and atlases built from them. A stale rebuild doesn't use up the asset's retry budget.

The full recipe reference is in [`asset-manifest.md`](skills/casual-mobile-art-director/references/asset-manifest.md#build-recipes-artpipeline-21).

## Placing into the engine

`place` writes approved files into the game project, moving aside anything it didn't write:

| Target | Writes | Atlases from `derive` also get |
|---|---|---|
| `xcassets` | Image sets and the app icon in your asset catalog | A `.spriteatlas` with one image set per frame |
| `godot` | Files in the project, each with an `.import` preset (existing ones are kept) | An `AtlasTexture` `.tres` per frame, plus `SpriteFrames` for animations |
| `phaser` | Files in the project plus a Loader pack file listing them | Atlas JSON and an `atlas` pack entry |
| `staging` | A folder plus `ART-INSTALL.md`, for read-only or unknown projects | `<name>.json` frame data |

## Install

```
/plugin marketplace add mrjoshuahoward/artpipelinetool
/plugin install artpipeline@artpipelinetool
```

On Claude Code 2.1.275 or later you can do it in one step:

```
/plugin install artpipeline --marketplace mrjoshuahoward/artpipelinetool
```

**Requirements:**
- Python 3.11+ on `PATH`. On first start the plugin builds its own environment in the plugin data folder; the log is `bootstrap.log` there.
- No system tools needed: SVG rendering is bundled.

If you previously uploaded `casual-mobile-art-director` to claude.ai, remove that copy so two versions of the skill don't compete.

## How a run goes

1. Ask for a handoff brief or for the assets. The brief ends with a `## Asset Manifest` (see [`skills/casual-mobile-art-director/references/asset-manifest.md`](skills/casual-mobile-art-director/references/asset-manifest.md)).
2. `init` loads it. The 2–4 **hero** assets are made first. You see them at real sizes and approve, then the style is locked.
3. The agent (and any subagents) build recipe assets or claim and produce the rest, registering each attempt. Failed checks and rejections come back with reasons; each asset gets 3 attempts, then it is flagged for you.
4. Every 15 approvals, work pauses until you've looked at a review sheet.
5. When you ask, `place` writes the approved files into your Xcode asset catalog, Godot project or Phaser `public/` folder.
6. `handback` gives you the final sheet, the manifest, flags, and the assets most likely to need a taste pass.

## CLI

Everything is also available as `artpipeline <command>` with JSON output: `init`, `status`, `claim`, `build`, `register`, `review-sheet`, `decide`, `lock-style`, `pass-gate`, `flag`, `unflag`, `history`, `place`, `handback`, `export-manifest`.

There are also stateless `check`, `process` and `contact-sheet` commands for one-off files.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                                   # unit, imaging parity, MCP (in-process and stdio)
claude --plugin-dir . # load the working copy as a plugin
claude plugin validate .

# evals (real, billed runs; the MCP server must actually start, hence --mocks off)
claude plugin eval . --scaffold --mocks off --allow-tools Write Edit Bash 'mcp__plugin_artpipeline_artpipeline__*'
```

The evals use the author's game **Sorting Line** as the test subject. It is private and not included here: each run's scaffold copies it from a local clone (`EVAL_SORTINGLINE_SRC`, default `~/developer/sortingline`), pinned to commit `06ba6cb` so results stay comparable as the game changes (`EVAL_SORTINGLINE_REF` overrides). Without a clone the scaffold stops with a clear error. To use your own game instead, point the scaffold at your repo and adjust the prompts and graders.

The design and milestones are in [`docs/v2/spec.md`](docs/v2/spec.md).

## License

MIT — see [LICENSE](LICENSE).
