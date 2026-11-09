# Asset Manifest (artpipeline v2)

Every handoff brief and every production run ends with a machine-readable `## Asset Manifest` section. It is the input to artpipeline's `init`. Write it as a fenced `yaml` block right after the heading. It is the twin of the human inventory table: the same assets with the same destinations.

## Shape

```yaml
version: 2
project: Sorting Line
direction: Factory Floor
style:
  block: >-                       # the fixed style paragraph, identical for every asset
    Flat vector badge, 6 px navy keyline, no gradients, no text, centred on a circular plate.
  palette: ["#22B8B0", "#F2C14E", "#23282B", "#F2F2F7"]   # hexes from the project's source files
  tokens: {teal: "#22B8B0", gold: "#F2C14E", ink: "#23282B", paper: "#F2F2F7"}
                                  # optional named colours for build recipes; omit palette to derive it
  backgrounds: ["#23282B", "#49606B"]                    # the game's real backgrounds (review sheets)
  references: [docs/art/refs/conveyor.png]               # optional starting references
settings:                         # optional; defaults shown
  max_attempts: 3                 # per asset, then flagged for the user
  gate_threshold: 15              # approvals between user review gates
  lease_minutes: 30
classes:                          # optional: project-specific classes (or use presets below)
  badge:
    format: png                   # png | webp | jpg | svg
    master: [1024, 1024]          # pixels (points for svg classes)
    alpha: forbidden              # required | forbidden | any
    display_sizes: [256, 64]      # contact-sheet sizes = how it is really seen
    review_backgrounds: ["#F2F2F7", "#1C1C1E"]
    renditions: []                # e.g. [{suffix: "@2x", scale: 2}] or [{suffix: "-512", size: [512, 512]}]
    processing: {palette_clamp: hard}   # trim, remove_bg, palette_clamp: hard|soft|off, flatten: "#hex"
    checks: {palette_min_share: 0.85}   # halo, palette_max_de, min_contrast, greyscale_read
groups:                           # optional: defaults shared by assets with that `group`
  tier1:
    build: {template: art-src/badges/frame.svg, params: {band: $gold}}
assets:
  - id: badge_first_shift         # lowercase, digits, _ . -
    class: badge
    subject: "Hard hat, three-quarter view, sitting on the plate"   # per-asset subject line
    acceptance_criteria:
      - "Hard hat reads as a hard hat at 64 px"
      - "Keyline separates the plate from iOS dark mode"
    destination: GameCenter/badge_first_shift.png   # relative to the output root
    hero: true                    # 2–4 heroes span the set's range; they are made and approved first
    group: tier1                  # optional, for batching
    needs_human_finish: false     # true for app icon, mascot, key art
    references: []
    overrides: {}                 # any class field, per asset (e.g. {alpha: required})
    build:                        # optional: artpipeline builds this asset itself (see below)
      source: art-src/badges/first_shift.svg   # merged over the group's build; params merge
```

## Presets (use by name in `class:`)

| Preset | Master | Alpha | Notes |
|---|---|---|---|
| `ios_app_icon_flat` | 1024×1024 PNG | forbidden | App Store icon; rounded-mask review on wallpapers |
| `ios_app_icon_layer` | 1024×1024 PNG | required | One Icon Composer layer |
| `game_center_badge` | 1024×1024 PNG | forbidden | Reviewed on iOS light and dark backgrounds |
| `store_screenshot` | 1320×2868 PNG | forbidden | iPhone 6.9" portrait |
| `sprite` | 512×512 PNG | required | Override `master`/`renditions` per project |
| `ui_icon_svg` | 44×44 pt SVG | required | Renditions @1x/@2x/@3x |
| `pixel_sprite` | 32×32 PNG | required | Nearest-neighbour only, integer factors |
| `tile` | 256×256 PNG | any | |
| `key_art` | 2048×1152 PNG | forbidden | Usually `needs_human_finish: true` |

## Rules

- `version: 2` is required. v1 manifests (`bird_sprite`, `ui_glyph`, `species`) are refused.
- Ids and destinations are unique. Destinations are relative paths without `..`.
- `subject` is only the per-asset line. The shared look lives once in `style.block`. The work packet combines them.
- Acceptance criteria must be testable at display size ("reads at 24 px against #23282B"), never "looks good".
- No named commercial products, app titles or IP in `style.block` or `subject`. Name the aesthetic directly.
- Mark 2–4 `hero: true` assets that span the set (most complex, simplest, one per colour group). If you mark none, the pipeline warns and still requires a style lock after the first `gate_threshold` assets.
- The master is the largest size you need. Raster renditions are only ever downscaled. If the engine needs 3×, make that the master.
- Code-drawn assets: write SVG and register it, even for PNG classes. It is rendered at the master size, and renditions are re-rendered sharp.

## Build recipes (artpipeline 2.1)

An asset with a `build:` entry is built by artpipeline from committed recipe files instead of a file you register. Use it for code-drawn sets (badges, UI icons, flat sprites, tiles), where it replaces throwaway generator scripts. Paths are relative to the pipeline root; keep them in the project (e.g. `art-src/`) and commit them.

- **`kind: svg`** (the default): `source` (this asset's SVG, a full document or a fragment) and/or `template` (a shared SVG with `<ap:slot/>` where the source goes), plus `params`.
- **`{{ name }}`** in any recipe file is replaced by `tokens.<name>` (a named colour), `params.<name>`, or `asset.id|subject|group|destination`. A bare name means a param, else a token. A param value `$gold` names a token. Unknown names are an error.
- **Slots:** in the source, `<ap:part name="title">…</ap:part>` fills `<ap:slot name="title"/>`; everything else fills the default slot. An unfilled slot keeps its own children.
- **`<ap:include src="parts/rivet.svg"/>`** inlines a shared part (relative to the including file). Local `<image href>` files are embedded.
- **Shapes** (expand to plain SVG; other attributes such as fill and stroke pass through; angles are degrees clockwise from 12 o'clock):
  - `<ap:star cx cy r points=5 inner=0.5 rotate=0>`
  - `<ap:polygon cx cy r sides rotate=0>`
  - `<ap:ring cx cy r width>`
  - `<ap:arc cx cy r start end sector=false>`
  - `<ap:gear cx cy r teeth depth=0.18 hole=0>`
  - `<ap:burst cx cy r rays inner=0 width=0.5>`
- **Text: `<ap:text font="../fonts/Title.ttf" font-size="96" x="512" y="835">{{label}}</ap:text>`** draws the text from a committed `.ttf`/`.otf` as plain outlines, so the built file never depends on the fonts of the machine that shows it. Plain `<text>` is refused. Options:
  - `text-anchor` (start|middle|end) and `valign` (baseline|top|middle|bottom, measured on cap height, so `middle` centres capitals in a banner).
  - `max-width` with `fit="wrap"` (break at spaces) or `fit="shrink"` (scale down until it fits: good for long localised titles).
  - `line-height` (×size, default 1.2), `letter-spacing` (px), `axes="wght=800"` for variable fonts, `<ap:br/>` for a line break.
  - fill, stroke, `paint-order="stroke"` and the like pass through to the path.
  - Shaping is simple (pair kerning, no ligatures or contextual scripts): fine for Latin, Greek and Cyrillic UI text. Check the font's licence allows embedding before committing it.
- Builds are deterministic, so artpipeline knows when a recipe, template, include, font, param or token change makes an asset **stale**, and `build(stale=true)` rebuilds exactly those.

### `kind: compose`: store screenshots, key art, layered icons

A compose recipe stacks layers, bottom to top, on a canvas the size of the class master. Each layer has exactly one of:

| Layer | What it draws |
|---|---|
| `svg: art-src/shots/sky.svg` | An SVG recipe file (tokens, params, shapes, `<ap:text>` all work). Layer `params` merge over the build's. |
| `image: art-src/shots/level3.png` | A local raster or SVG file, embedded: a gameplay capture, a painted background, a device frame. |
| `asset: first-bloom` | Another asset's **approved** output. Key art from approved sprites, an icon on a banner. |
| `text: "{{params.caption}}"` | Outlined text: needs `font` and `font_size`; `color`, `anchor`, `valign`, `max_width` + `shrink`, `line_height`, `letter_spacing`, `axes`, `stroke` + `stroke_width`. Newlines break lines. |
| `fill: $gold` | A solid rectangle (rounded with `radius`). |

Every layer takes `at: [x, y]`, `size: [w, h]` (default: the whole canvas), `fit` (contain|cover|stretch), `radius` (rounded clip for image, asset and svg layers), `opacity`, `rotate` (degrees about the box centre) and `shadow: {dx, dy, blur, color, opacity}`. Colours are `#RRGGBB`, `$token` or `{{...}}`. The build also takes `background` and `params`.

```yaml
  - id: shot-1
    class: store_screenshot
    build:
      kind: compose
      params: {caption: "Sort the garden\nbefore it blooms"}
      layers:
        - {svg: art-src/shots/sky.svg}
        - {image: art-src/shots/level3.png, at: [170, 760], size: [980, 2125], fit: cover, radius: 64, shadow: {dy: 24, blur: 48}}
        - {text: "{{params.caption}}", font: art-src/fonts/Title.ttf, font_size: 120, at: [660, 400], anchor: middle, valign: middle, max_width: 1100, shrink: true, color: $cream}
```

### `kind: derive`: sprite sheets and texture atlases

Packs other assets' **approved** outputs into one PNG the size of the class master. Use class `sprite_atlas` (2048×2048, alpha) with `overrides: {master: [..]}` for the texture size the engine wants.

```yaml
  - {id: coin-spin, class: sprite_atlas, subject: Coin spin, acceptance_criteria: [Loops smoothly],
     destination: sprites/coin-spin.png, overrides: {master: [512, 128]},
     build: {kind: derive, layout: grid, frames_group: coin, padding: 0,
             animation: {fps: 10, sequence: [coin-0, coin-1, coin-2, coin-1]}}}
  - {id: ui-atlas, class: sprite_atlas, subject: UI atlas, acceptance_criteria: [All icons present],
     destination: ui/ui.png, overrides: {master: [1024, 1024]},
     build: {kind: derive, frames: [btn-play, btn-pause, icon-star], extrude: 1}}
```

- **`frames`** (asset ids) or **`frames_group`** (every other asset in that group, in brief order). Each frame appears once. Repeat frames in `animation.sequence`.
- **`layout: grid`**: a sprite sheet. Equal cells, frames centred, `columns` optional. **`layout: pack`** (the default): an atlas. Frames are trimmed of transparent borders (`trim: false` to keep them) and packed.
- **`cell: [w, h]`** scales every frame to fit (vector frames need it; pixel art only by whole numbers). **`padding`** (default 2) and **`extrude`** (repeat edge pixels: 1–2 for filtered sprites) stop texture bleeding.
- If the frames don't fit, the build says what size they need. The class can't trim, remove backgrounds or make renditions, because those would move the frames.
- `place` writes the frame table for the engine: Phaser atlas JSON and an `atlas` pack entry; Godot `AtlasTexture` per frame plus `SpriteFrames` for animations; an Xcode `.spriteatlas`. Staging writes `<name>.json` beside the sheet.

### `kind: script`: the fallback

When `svg`, `compose` and `derive` can't express an asset (procedural noise, a custom raster effect, an existing drawing script), commit a script and let artpipeline run it. Prefer the other kinds: their recipes stay readable and their stale tracking is exact.

```yaml
groups:
  terrain: {build: {kind: script, script: art-src/scripts/terrain.py,
                    inputs: [art-src/scripts/lib/*.py, art-src/textures/*.png], tokens: [grass, soil]}}
assets:
  - {id: tile-meadow, class: tile, subject: Meadow tile, acceptance_criteria: [Tiles seamlessly],
     destination: tiles/meadow.png, group: terrain, build: {params: {seed: 7, density: 0.4}}}
```

- The script runs in an empty temp directory holding **only** the script and its declared `inputs` (paths or globs), at the same relative paths. A file it reads but didn't declare isn't there, and the build fails saying so, so the recorded inputs are complete.
- `.py` runs with artpipeline's own Python, so Pillow, resvg-py and `artpipeline` are importable. `.sh` runs with `/bin/sh`; anything else must be executable.
- The job: `from artpipeline.build.script import job; j = job()` (or read the JSON file at `argv[1]`). It holds `asset` (id, subject, group, destination), `params`, `tokens` (only those listed in `tokens:`, or all when omitted), `master`, `pixel_art`, `assets` (id → path of each approved dependency listed in `assets:`) and `output`, the file to write: `.svg` for vector classes, else `.png`.
- The environment is fixed (TZ=UTC, PYTHONHASHSEED=0, SOURCE_DATE_EPOCH=0, HOME is the temp dir), with no secrets from the caller. `timeout` defaults to 60 s (max 600). Don't use the network.
- **Staleness hashes the inputs, not the output,** so `status()` never runs a script. Listing `tokens:` keeps unrelated palette edits from making it stale. If an edited script still writes the same file, `build` refreshes the record and the asset stays approved.
- **Make it deterministic:** seed randomness from a param, and don't use timestamps or set ordering. `build(dry_run=true)` runs a script twice and warns when the bytes differ.

An `asset` layer builds only once that asset is approved (otherwise `BUILD_FAILED`, no attempt used). The same goes for derive frames and script `assets`. When the layered asset or frame is rebuilt and approved again, the compose or derive asset becomes stale, so a palette change flows through as: `build(stale=true)` → approve the rebuilt parts → `build(stale=true)` again for the composites.
