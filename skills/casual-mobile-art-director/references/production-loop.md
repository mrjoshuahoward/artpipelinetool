# Production Loop — Making the Assets, Not Just Specifying Them

Read this when the user wants you to **produce the art yourself**: generate, draw, process, check and place real asset files, rather than write a brief for someone else. This file covers how to run the loop. `ai-production-tooling.md` covers which tool to use for each asset class.

## 0. Preconditions (settle these quickly, ask only what's missing)

| Need | Where it comes from | If missing |
|---|---|---|
| An approved direction | An art spec in the repo, a brief from this conversation, or the user's description | Run a short tightening pass first (pillars, palette, silhouette rules). Don't generate against a vague direction |
| The asset list | The brief's inventory, or the user's request | Draft a short inventory table and confirm the **first batch** only |
| Where files go | The user's instruction or the repo layout | Ask once. Default: the engine's real asset directories in the project. **If the user says read-only, write to a separate output folder** and hand over install steps |
| Tools | Connected MCP tools, APIs, and local CLIs you can verify (`which inkscape rsvg-convert ffmpeg blender`) | Plan around what exists. Claude-authored SVG plus the bundled scripts always works |
| Budget | Paid generators bill per image or credit | Estimate the count before a large batch (e.g. "46 badges × ~3 attempts ≈ 140 generations") and get a yes |

## 1. Style lock before volume

1. **Pick 2–4 hero assets** that span the set's range (e.g. the most complex badge, the simplest, one per colour group).
2. Produce them, run the checks (step 3), and build a **contact sheet** (`scripts/contact_sheet.py`) at real display sizes on the game's real backgrounds.
3. **Sign-off gate:** show the user the sheet and the decisions it embodies. Only after a yes do you lock the style:
   - **The style block:** a fixed prompt paragraph, or for code-drawn assets, a shared SVG/shader template with the stroke width, corner radius, palette tokens and light direction.
   - **References:** the approved heroes become the reference images, style ID or trained style for everything after.
   - **The palette file:** hexes taken from the project's source files, saved next to the assets for `--palette`.
4. Record the lock in the manifest (step 6). From here on, every asset is generated *against* the lock, not freshly.

If the user is away or explicitly says "just make them", still make the heroes first, check them yourself, and say in the hand-back that the remaining batch was generated against a lock that hasn't been approved.

## 2. Choose the production route per asset

Prefer, in order (pick the first that can hit the style):

1. **Code-native:** an SVG you write directly, the engine's procedural drawing code, a shader, or particles. It's free, deterministic, always on-palette and easy to revise. Most flat, vector, geometric, icon, badge and UI work belongs here. If the game already draws its pieces in code (as many Phaser and Godot games do), **reuse that geometry** so store art and badges stay on-model.
2. **Agent-driven app:** VectorCraft, PhotoCraft or EffectCraft MCP, the Blender connector, Figma or Canva. Use these when you need the app's operations (boolean ops, PSD layering, Lottie export, 3D renders, layout templates).
3. **Image generation:** painterly, illustrated, photographic or textural looks that code can't reach; volume after a style lock; hero drafts that a human will finish. Give it a real role when the style calls for it. Don't confine it to concepts out of caution. Always follow generation with steps 3–4.

## 3. Generate → check → fix (per asset, scripted where possible)

```
generate / draw
  → post-process: background removal if needed, trim, palette_clamp.py (flat styles: hard; painterly: --soft 0.3)
  → export_sizes.py to the engine's sizes (@2x/@3x, atlas frames, 1024 store art; --flatten for no-alpha targets)
  → check_asset.py: size, alpha rules, halo, palette share, contrast vs real backgrounds (non-zero exit = fail)
  → look at it: render on the contact sheet at the real in-game size; check the silhouette in greyscale
  → pass? next asset : fix the cause and retry
```

- **Retry budget:** at most 3 attempts per asset, changing the *cause* each time (the prompt subject line, the reference, a seed, or the geometry), not rerolling blindly. After 3, flag the asset for the user, with the attempts on a sheet.
- **Judge at display size, never at generation size.** A badge seen at 64 px gets judged at 64 px.
- **Judge on the backgrounds the platform will use, not only the game's.** Game Center and the App Store show art on iOS light and dark system backgrounds (around `#F2F2F7` and `#1C1C1E`); app icons sit on arbitrary wallpapers. Put those on every contact sheet. Dark-plate badges need a light rim or outer keyline to separate from dark mode.
- **Hard checks come from the platform and the brief:**
  - App Store icon, screenshots and Game Center art have no alpha.
  - Icon layers have crisp edges and no baked gloss.
  - Sprites have transparent corners.
  - Silhouettes must read in greyscale.
  - Each asset must clear the brief's own acceptance criteria.
- Never AI-upscale pixel art; `export_sizes.py --pixel` scales with nearest-neighbour at integer factors.

## 4. Human-finishing flags

Mark any asset where human authorship matters (app icon, mascot, key art) as `needs-human-finish` in the manifest. That isn't an App Store rule. It matters for copyright and IP protection, and for the "doesn't look generated" bar. Code-native and Claude-authored SVG assets don't need the flag for originality reasons, but they still need the user's taste sign-off at the gates.

## 5. Integrate and verify in the engine

The asset isn't done until it looks right **in the game**:

- **Place files** where the engine expects them:
  - Asset catalog image sets with `Contents.json`.
  - Godot import presets.
  - A Phaser atlas plus its preload-manifest entry.
  - For the app icon, the Icon Composer layer files.
- **Pack atlases** (TexturePacker CLI, or the engine's own packer) when the set is final.
- **Screenshot in context:**
  - Phaser: the dev server plus Playwright on the real canvas.
  - Godot: the Godot MCP or a headless run.
  - Native: the iOS simulator.
- **Compare against the contact-sheet expectation.** Watch for resolution softness (the DPR cap), wrong import filters, premultiplied-alpha fringes and colour-space shifts.
- **Read-only repo:** do everything in the output folder, write `INSTALL.md` with exact copy steps and any config changes, and verify against a scratch copy or a branch the user owns. Never touch their working tree.

## 6. Manifest (always write one)

`art-manifest.json` (or `.md`) next to the assets, with one row per file:

```json
{ "file": "badges/sortingline.first_shift.png", "size": "1024x1024", "route": "code-native SVG",
  "tool": "Claude SVG + export_sizes.py", "prompt_or_source": "badge-template.svg, glyph=hardhat",
  "model": null, "seed": null, "style_lock": "v1 (approved 2026-11-04)",
  "checks": "check_asset pass; contact sheet v3", "status": "approved | pending | needs-human-finish",
  "rights": "original (code-authored)" }
```

The manifest makes regeneration reproducible, supports rights questions (which model and which terms), and is how the user audits a 46-item batch without opening 46 files.

## 7. Review gates and hand-back

- **Gates:** style lock (step 1), first full batch (a contact sheet of everything), in-engine screenshot (step 5). Never more than about 15 new assets between gates without a sheet.
- **Hand-back:** a contact sheet, the manifest, the in-engine screenshot, a list of failures and flags, and the 3–5 assets most likely to need taste revisions. Revisions update files in place and append to the manifest. Don't fork copies.
- **Don't overwrite existing art without confirmation.** Version superseded files (`_v1`) or move them to `superseded/` until the user approves.

## Bundled scripts (Pillow; SVG via rsvg-convert, Inkscape, cairosvg or Playwright, whichever exists)

| Script | Use |
|---|---|
| `scripts/contact_sheet.py out.png a.svg b.png --sizes 256,64,24 --bg "#23282B,#49606B" [--icon-mask]` | Review sheet at true sizes on real backgrounds, plus a greyscale row |
| `scripts/check_asset.py *.png --palette pal.txt --bg ... [--expect-alpha / --no-alpha] [--size 1024x1024]` | Objective gate; JSON out, non-zero exit on fail |
| `scripts/palette_clamp.py in.png out.png --palette pal.txt [--soft 0.3]` | Snap generator drift to the brief palette |
| `scripts/export_sizes.py master.svg out/ --name x --points 44` or `--px 512,1024 [--pixel] [--flatten "#hex"]` | Engine and store sizes; re-rasterises SVG per size; refuses raster upscales |

Run them with the skill's `scripts/` directory as the working directory, or by absolute path (they import `_common.py` from beside themselves).
