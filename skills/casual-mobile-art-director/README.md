# casual-mobile-art-director

A Claude skill that acts as an **art director and art producer for casual mobile games** built in native Swift/iOS, Godot or Phaser (shipped to iPhone through Capacitor). It turns a mechanic or pitch into visual directions and briefs, and it can also **make the assets itself**: icons, sprites, badges, UI, store screenshots and key art, using whatever tools are connected (image generators, Canva, Figma, the ArtCraft apps such as VectorCraft, Blender) plus the check scripts bundled here.

It works in both **claude.ai** and **Claude Code**.

## Modes

| Mode | Use it when | What you get |
|---|---|---|
| **Ideation** | You have a mechanic or pitch but no look yet | 3 genuinely different directions, each with a metaphor, precedent, risk, pipeline line and moodboard |
| **Tightening** | You already know the direction | Contradictions and risks surfaced, questions asked in batches, then a brief. No alternatives |
| **Deep-dive** | A direction is chosen; write it up | A discussion brief, or a handoff brief another agent can execute |
| **Production** | You want the actual files | A style-lock batch, then generate → check → fix, in-engine verification, a manifest and contact sheets at review gates |

Claude picks the mode from how you ask. For example, "give me options" runs ideation, "pressure-test this" runs tightening, and "make the badges" runs production.

## Layout

```
SKILL.md                         modes, flows, behaviour rules (loaded when the skill triggers)
references/
  ai-production-tooling.md       agent-drivable tools, asset-class → tool routing, style-lock patterns, rights
  production-loop.md             how production mode runs: preconditions, gates, checks, manifest
  pipeline-phaser.md             Phaser 3/4, atlases, Capacitor/WKWebView, DOM-over-canvas seam
  pipeline-swift-ios.md          asset catalogs, SpriteKit/RealityKit, Liquid Glass, Icon Composer, store specs
  pipeline-godot.md              Godot 4.4–4.7 import, shaders, iOS export, MCP
  casual-mobile-canon.md         touchstone titles and current trends (dated; verify with web search)
  style-vocabulary.md            precise words for render style, colour, lighting, motion, UI material
scripts/                         Pillow-based helpers used in production mode (run with --help)
  contact_sheet.py               assets at true display sizes on real backgrounds, plus greyscale
  check_asset.py                 pass/fail gate: size, alpha rules, halo, palette share, contrast
  palette_clamp.py               snap generated rasters to the brief palette
  export_sizes.py                @1x/@2x/@3x, store sizes, pixel-art scaling, flatten for no-alpha targets
  _common.py                     colour maths and SVG rendering (rsvg-convert → Inkscape → cairosvg → Playwright)
evals/                           test cases in the `claude plugin eval` layout (excluded from the package)
```

**Script requirements:** Python 3 with Pillow. Rendering SVG also needs one of `rsvg-convert`, Inkscape, `cairosvg` or Playwright Chromium. PNG inputs work without any of them.

## Install

The packaged file is a standard zip with the skill folder at its root. Build it as described under Development below.

- **claude.ai:** go to Customize → Skills → Upload and choose the `.skill` file (rename it to `.zip` if the uploader insists). Code execution must be on. Remove any older copy first, including one installed through a plugin, so two versions don't compete. The upload syncs to Claude Code automatically; start a new session to pick it up.
- **Claude Code only:** copy the folder to `~/.claude/skills/casual-mobile-art-director/`. Don't do this if the claude.ai copy is also syncing, or you'll have two skills with the same name.

## Development

1. Edit the skill in this repo.
2. Run the evals. They use the in-development game **Sorting Line** (`~/developer/sortingline`, treated as read-only) as the test subject:
   - `icon-directions-greenfield`: icon and launch-screen directions
   - `meta-screens-tightening`: pressure-test a direction and write a discussion brief
   - `store-assets-handoff`: a handoff brief for App Store and Game Center art
   - `achievement-badges-production`: actually make all 46 Game Center badges

   Run them with the skill-creator skill (parallel runs plus the review viewer), or from the skill folder with `claude plugin eval . --allow-tools Write,Edit,Bash`. These are real, billed model runs.
3. Package with skill-creator's packager, which leaves `evals/` out:
   ```bash
   cd <skill-creator dir> && python3 -m scripts.package_skill <this repo> <output dir>
   ```
4. Re-upload to claude.ai, replacing the previous version.

## History

- **2026-11:** a major update.
  - **Production mode** with bundled check scripts.
  - **AI and creative-app tooling** reference (ArtCraft apps from `github.com/storytold`, Canva, Figma, Adobe, Blender, Recraft, Scenario, Retro Diffusion, Ludo, current image models).
  - **Phaser** pipeline added, **Unity** dropped.
  - **Refreshed for current versions:** iOS 27, Liquid Glass, Icon Composer, the deprecation of SceneKit, Godot 4.7 and the 2025–26 canon.
  - **Rules added:** quote sources and label guesses, respect read-only boundaries, name any departure from a project's signed-off pillars, and route work only to connected tools.
  - **Works in both** claude.ai and Claude Code.
  - **Evals:** across 4 iterations on Sorting Line, the updated skill passed 100% of checks; the May 2026 version passed 63%.
- **2026-05:** first version, for claude.ai.
