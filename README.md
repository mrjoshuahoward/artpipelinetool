# artpipeline

> **This is v2 (Nov 2026).** The original v1 (May 2026, a browser-driven CLI) is at tag [`v0.1.0`](../../tree/v0.1.0).

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

artpipeline doesn't call AI image generators. It produces assets in two ways:
- **It builds them itself from recipes (2.1).** These are SVG templates and per-asset sources committed with your project, coloured from named style tokens and drawn with a small shape library (`<ap:star>`, `<ap:gear>` and so on). Builds are deterministic, so after a palette or frame change, `build(stale=true)` rebuilds exactly the affected assets.
- **The agent produces them with whatever fits:** connected generators, VectorCraft/PhotoCraft, Canva, Blender.

Either way, artpipeline records, processes, checks and gates the result.

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
3. The agent (and any subagents) claim assets, produce them, and register each attempt. Failed checks and rejections come back with reasons; each asset gets 3 attempts, then it is flagged for you.
4. Every 15 approvals, work pauses until you've looked at a review sheet.
5. When you ask, `place` writes the approved files into your Xcode asset catalog, Godot project or Phaser `public/` folder, moving aside anything it didn't write.
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
