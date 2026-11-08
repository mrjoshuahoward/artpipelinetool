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
