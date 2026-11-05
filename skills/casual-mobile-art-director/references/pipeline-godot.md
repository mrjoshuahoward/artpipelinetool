# Godot Pipeline — Asset Production & Integration Notes

Working knowledge for advising on a Godot art pipeline. Verified Nov 2026: current stable is **Godot 4.7.x** (4.8 in development). Ask which version the project is on — features below are tagged with the release that introduced them.

## What changed recently that matters for art (4.4 → 4.7)

- **4.4** — native **Metal** backend on Apple silicon (replaces MoltenVK); 2D batching on all renderers; CanvasItem **instance uniforms** (per-sprite shader params without unique materials — great for palette/tint variants); ubershaders cut shader stutter.
- **4.5** — **shader baker** precompiles shaders at export (big cold-start win on Metal — removes the "first effect hitches" problem); Mobile renderer uses FP16; TileMapLayer chunked physics; visionOS export (windowed).
- **4.6** — scene tiles rotate in 90° steps; Mobile renderer debanding (helps gradient-heavy skies); glow blends before tonemapping; AgX tonemapper controls.
- **4.7** — **2D Scene Paint** mode (scatter props/scenes without a grid — level dressing gets much faster); `DrawableTexture2D` for runtime drawing; AtlasTexture in TextureRect incl. nine-patch; GradientTexture2D conic fill; font-relative images in RichTextLabel (inline icons in text); `Tween.tween_await()`; built-in VirtualJoystick; HDR output on iOS.
- **Renderer choice:** the Mobile renderer now matches or beats Compatibility in some benchmarks; default to Mobile for iOS unless targeting very old devices. Note the iOS Simulator only runs Compatibility, so visual sign-off must happen on device.

## Asset import discipline

Godot reimports assets on change; your import settings are part of the art direction. Set them deliberately, not by default.

**Texture import settings that matter:**
- **Filter (Nearest vs Linear)** — `Nearest` for pixel art, low-poly hard-edge looks. `Linear` for everything painterly or smooth. Wrong choice murders the aesthetic.
- **Mipmaps** — on for 3D and any sprite that scales. Off for pixel art and UI that's always at native size.
- **Compression mode** — `Lossless` for UI and pixel art, `VRAM Compressed` for 3D textures and large environments, `Lossy` (WebP) for big sprites where artifacts won't show.
- **Fix Alpha Border** — on for any sprite with transparency, off for fully-opaque atlases. Forgetting this causes the dreaded dark fringe.
- **HDR** — almost never needed for casual mobile (4.7 can output HDR on iOS, but it's an art-direction choice, not a default).
- **SVG** — Godot rasterizes SVG at import via ThorVG (limited feature support: avoid filters, masks, embedded text). Import as DPITexture if you need runtime re-rasterization at multiple scales. Clean AI-generated or Canva/Figma SVG exports before import.

**Re-import preset workflow:** Define import presets in Project Settings for each asset class (pixel UI, painted sprite, 3D albedo, etc.) and assign by folder. Saves hours over the project's life.

## Sprite atlases

Godot has built-in atlas support via `AtlasTexture`, but TexturePacker remains the most flexible external tool. For most casual projects:

- **Per-scene atlases** rather than one mega-atlas — keeps memory loads scoped.
- **Power-of-two textures** still help on older mobile GPUs even though Godot 4 doesn't strictly require them.
- **Trim transparent space**, but keep the original size metadata so positioning works.
- **Premultiplied alpha** for any sprite with semi-transparent edges — eliminates fringing on scale.

For animation frames, evaluate `AnimatedSprite2D` (sprite-sheet driven) vs. a single `Sprite2D` driven by `AnimationPlayer` keyframes. Sprite-sheet wins for short loops; AnimationPlayer wins for cutscenes and complex multi-property animation.

## 2D rendering hierarchy

- **CanvasLayer** for UI that should ignore camera transforms.
- **Node2D** as default game-world parent.
- **Y-sort** on parent nodes for top-down/isometric depth.
- **Light2D + LightOccluder2D** for 2D dynamic lighting — surprisingly cheap on modern mobile, can transform a flat-lit scene.

## Theme resources for UI

Casual games live in their UI. Build a `Theme` resource with all your typography, colors, and control styles in one place. Lets you skin the entire game by swapping the theme — useful for white-label or seasonal events. Custom `StyleBoxFlat`, `StyleBoxTexture` give you 9-slice rounded panels without re-exporting art.

## Shader-driven art direction

For casual mobile, shaders are an underused art-direction lever:

- **Palette swap shader** — single grayscale sprite + ramp texture = full character recoloring without re-exporting. Huge for cosmetics.
- **Outline shader** — runtime outlines on selection / hover, cheaper than pre-baked.
- **Dither / posterize shader** — fakes a limited-palette look on smooth-rendered art.
- **Risograph shader** — registration-offset color channels + grain. Distinctive at low cost.
- **Wind / wobble vertex shader** — gives 2D foliage life without animation frames.
- **2D water shader** — sin-wave UV distortion, a few cents of GPU time, sells the world.

Shaders run on `CanvasItemMaterial` (light/blend tweaks) or `ShaderMaterial` (custom). Use **instance uniforms** (4.4+) for per-sprite variation so many sprites share one material and batch. Enable the **shader baker** (4.5+) on iOS exports to kill cold-start compile hitches. Still test on the lowest-spec target device.

## Animation tooling

- **Sprite sheets** from Aseprite (built-in export) or Krita.
- **Cutout / rigged 2D** — Spine (paid, gold standard) integrates via `spine-godot`. DragonBones (free) integrates with the godot-dragonbones plugin. Godot's native `Skeleton2D` + `Polygon2D` is workable for simple rigs and ships without dependencies.
- **3D rigs** — glTF is Godot's first-class format. Bake animations in Blender, export .gltf or .glb. Avoid FBX for new projects.
- **Lottie / vector animation** — `gd-lottie` plugin works but is fiddly; for casual UI motion, hand-keyed AnimationPlayer (or Tweens) is usually better.
- **spine-godot** — actively maintained; confirm a build exists for the project's exact Godot minor version before committing to Spine (runtime builds lag engine releases).

## 3D-rendered-to-2D pipeline

For the Royal Match school of look:

1. Model and shade in Blender (Eevee for speed, Cycles for quality).
2. Render orthographic, alpha-channel PNG.
3. Bring into Godot as a regular Sprite2D. Treat the 3D as offline-only.
4. For animations, render frame sequences and pack into a sprite atlas.

Cost is real — every visual variant is a render. Plan for it.

## Performance gotchas on mobile

- **Texture memory ceiling** — many older iOS devices choke above ~150 MB of resident texture. Atlas aggressively, mipmap, compress.
- **Draw calls** — every distinct material or atlas is a draw call. Combine where possible. `MultiMeshInstance2D` for many copies of the same sprite.
- **Particle counts** — `GPUParticles2D` is fine on modern mobile, less so on old. Have a "low FX" toggle.
- **Shader complexity** — branchy fragment shaders kill performance on older GPUs. Profile on the actual minimum device.
- **Pixel-perfect viewport** — for pixel art, set the project to integer scaling and a base resolution. Godot's `Stretch Mode: viewport` + `Aspect: keep` is the usual config.

## Export pipeline for iOS

- iOS export requires a Mac with Xcode. Godot 4.7 minimum: iOS 16 (Metal) / iOS 15 (Vulkan).
- **App icon:** Godot's export preset takes PNGs; for iOS 26+ layered Liquid Glass icons, finish the icon in Xcode with Icon Composer (see `pipeline-swift-ios.md` → App icons).
- Launch screen via `LaunchScreen.storyboard` — Godot will generate one but custom is usually wanted.
- App Store screenshots: render at required device resolutions; consider doing them as in-engine scenes with a "screenshot mode" rather than exporting from gameplay.

## Agent tooling

- **Godot MCP servers** exist that drive a live editor (e.g. `godot-editor-mcp`, Godot 4.4+, works with Claude Code) — scene editing, node creation, resource import, screenshots. If connected, use it to place assets, apply import presets, and screenshot results for review rather than hand-writing `.tscn`/`.import` files. Verify which server the user has; tool sets differ.
- Without MCP, Godot's text formats (`.tscn`, `.tres`, `.import`) are agent-writable — but import settings written by hand must be reimported in-editor to take effect.
