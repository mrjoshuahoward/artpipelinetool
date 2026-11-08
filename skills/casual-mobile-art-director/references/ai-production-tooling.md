# AI & Creative-App Production Tooling — What an Agent Can Actually Drive

Production levers available to an LLM agent, either directly (MCP servers, connectors, CLIs) or through a user-run app. Surveyed **November 2026**. This space changes month to month: before committing a brief to a specific tool, **check what is connected in this session** (list available MCP tools or connectors) and use web search to confirm model names and versions. Items marked *(unverified)* came from third-party sources only.

## How to use this file

1. **Inventory first.** At the start of any production-planning step, check which creative tools are connected (in Claude Code, the MCP tools in this session; in claude.ai, the enabled connectors). Plan around what is actually there. Recommend adding a tool only when it removes a real bottleneck.
2. **Match each asset class to a lever** using the routing table below. One direction usually needs 3–5 tools, not 15.
3. **Producing it yourself?** Follow `production-loop.md` for the loop, using this file for routing.
4. **Write the tool chain into the brief.** In a handoff brief, every asset row names its production tool, its prompt seed or command, and an acceptance check the agent can run itself (render, preview or screenshot, then compare with the reference).

## Routing table — asset class → best lever

| Asset class | First choice | Alternatives | Notes |
|---|---|---|---|
| UI icons, flat/geometric sprites, logos | Claude writes SVG directly, then **VectorCraft** MCP cleans up, previews and exports | **Recraft** (native SVG generation with a style ID), Figma | Native vector beats tracing a raster. Both VectorCraft and Recraft let the agent check its own output |
| Painted/illustrated sprites, props, characters | Image model with reference images (**Nano Banana Pro / 2.x**, **gpt-image-2.x**, FLUX) | **Scenario** (custom-trained style model) for large sets | Lock style with reference images or a trained model. Use native alpha where offered |
| Large consistent sets (50+ tiles, cosmetics, a character roster) | **Scenario** trained style model on the user's own approved art | Recraft custom style, Nano Banana multi-reference (up to about 14 references) | Train after 10–20 hero assets are approved, not before |
| Pixel art | **Retro Diffusion** MCP (official, includes a Claude Code plugin) | PixelLab *(unverified)*, Aseprite CLI/MCP for editing | Never AI-upscale pixel art; scale nearest-neighbour |
| Sprite-sheet animation | **Ludo.ai** (static sprite → sheet + atlas data), Retro Diffusion for pixel | Blender render of 3D, Spine | Assemble with Aseprite CLI, pack with TexturePacker CLI |
| 3D-rendered-to-2D (Royal Match / toy-block look) | **Meshy** / Tripo / Rodin / Hunyuan3D mesh → **Blender** connector renders orthographic alpha frames | TextureCraft to re-texture | Blender's official connector runs Python against the live scene. Turntables and sprite renders are scriptable |
| Textures / PBR | **TextureCraft** MCP | Image model, then tile/seam fix | Mostly for RealityKit or Godot 3D |
| UI layout, HUD, design tokens | **Figma** MCP (write via `use_figma`, needs a paid plan and edit access) | Claude writing SwiftUI/Godot Theme/Phaser config directly | Figma variables pair naturally with colour tokens shared across engines |
| UI motion / micro-animation | **Rive** MCP (Early Access editor) or **Lottie Creator** MCP | **EffectCraft** (Lottie import/export), hand-keyed in engine | Check the engine's runtime support first (Phaser has no Lottie or Rive plugin; see `pipeline-phaser.md`) |
| Raster cleanup, batch resize/trim/recolour, PSD assembly | **PhotoCraft** MCP/CLI (headless batch) | Adobe connector, Affinity connector (scriptable) | The post-generation cleanup pass: halos, trims, palette clamp |
| Skeletal animation | **Spine** (official CLI for export + pack) | Godot Skeleton2D, community Spine MCPs | Needs a Spine licence |
| Atlas packing | **TexturePacker** CLI | Godot built-in atlas, Xcode `.atlas` folders | Use the engine's native format |
| Store screenshots, promo art, social | **Canva** connector (brand kits, `resize-design`, `export-design`) | Figma, Adobe Express via the Adobe connector | Canva Pro needed for transparent/lossless PNG and brand-kit tools. Not for in-game assets |
| Trailer / App Preview video | **EffectCraft** (MP4/ProRes) | Canva video, in-engine capture | App Previews: 15–30 s, ≤30 fps |
| Logo / title card with text | **Ideogram** (`generate-transparent` endpoint) | Recraft, hand-built vector | Outline text before any SVG goes into an icon layer |
| In-engine placement and verification | **Godot** MCP (community: godot-editor-mcp, Coding-Solo/godot-mcp, GDAI), **Phaser Editor** MCP | Write scene files directly | Screenshot the result in-engine; acceptance happens there, not in the generator |

## Tool notes

### The ArtCraft line (open-source "Crafting Apps")
Open-source desktop apps written in Rust (MIT/Apache-2.0), most also running in the browser via WebAssembly. Their GitHub org is `storytold`; Storyteller is the team's earlier name. **Every menu command is also exposed through a CLI, a JSON control channel and a local stdio MCP server**, so Claude Code can drive them headless and check its own output with the render-preview tools. Most are self-described **alpha**: suitable for production help, but have a fallback ready.

**Canonical source: `github.com/storytold`** (for example https://github.com/storytold/photocraft); the user has confirmed it. **Imposter repos and look-alike packages exist.** Install and recommend only from the storytold org, and check that any CLI/MCP package traces back to it before running it.

- **VectorCraft** (Illustrator-style editor)
  - Setup: `claude mcp add vectorcraft -- vectorcraft-cli mcp`. Limit file access with `--automation-read-root` / `--automation-write-root`.
  - Tools: `draw_shape`, `draw_path` (takes SVG path data), `add_text`, `set_paint`, `pathfinder`, `transform`, `apply_effect`, `command_batch` (up to 256 steps), `inspect_document`, `render_preview`/`screenshot`, `export`.
  - Exports: SVG/PDF/EPS/PNG/WebP, plus Export for Screens (handy for @2x/@3x).
  - Limits: the team rates it about 65% of what an illustrator needs. No AI generation; Image Trace is unconfirmed.
- **PhotoCraft** (Photoshop-style raster editor): 500+ commands, reads and writes PSD/PSB, and `photocraft-cli batch` processes whole folders. Use it as the cleanup stage after generation.
- **EffectCraft** (motion graphics): imports and exports Lottie; renders MP4, ProRes and image sequences. Use for UI motion and trailers.
- **TextureCraft** (3D texture painting): PBR maps, textured GLB/USD.
- **Other siblings:** DesignCraft, FigCraft, LightCraft, MaterialCraft, FilmCraft and more. Check the org for current status before recommending them.
- **ArtCraft** (the AI studio itself): a desktop app that aggregates about 60 image, video and 3D models (Nano Banana, GPT Image, FLUX, Seedream, Meshy, Tripo, Midjourney via the user's own account). It has no official MCP; one community MCP exists but is unofficial. Use it as the user's hands-on generation tool, not an agent lever.

### Canva
A remote MCP connector with about 45 tools:
- **Creating:** `generate-design`, `create-design`, editing transactions (start → perform → commit).
- **Images:** `generate-image`, `remove-background`, `separate-image-layers`.
- **Output:** `resize-design`, `export-design` (PNG/JPG/PDF/PPTX/GIF/MP4).
- **Brand:** brand kits and brand templates with `autofill-design`.

Use it for **marketing: store screenshots, promo banners, social and press kits**. It's a poor fit for sprites. Limits: transparent PNGs and brand-kit tools need Pro, rate limits are about 10–20/min on generate and export, and premium elements can return `license_required`. The **Affinity by Canva** connector can script Affinity (batch export, renaming) while both apps are open.

### Other connectors
- **Figma:** writes to the canvas via Plugin API JS (paid plan). Best for UI kits and design tokens; vector drawing isn't documented.
- **Adobe for creativity:** an official connector with 50+ tools across Photoshop, Illustrator, Firefly, Express, Lightroom and Stock. Roughly Express-level power. Whether it exposes Firefly generation is *(unverified)*.
- **Blender (official, Blender 5.1+):** runs Python against the live scene with no sandbox. Use it for 3D → 2D sprite renders, turntables and mesh cleanup.

### Image models (verify current names before writing them into a brief)
- **OpenAI gpt-image-2.x:** native transparent PNG/WebP. gpt-image-1 was shut down in Oct 2026.
- **Google Nano Banana Pro / 2.x (Gemini image):** strongest multi-reference consistency (up to about 14 references), 4K output, extreme aspect ratios. Every image carries a SynthID watermark. No documented native alpha, so plan a background-removal pass.
- **FLUX (Black Forest Labs):** multi-reference editing.
- **Ideogram:** best at text; has a transparent endpoint.
- **Recraft:** native SVG, style IDs, vectorising, upscaling. Remote MCP at `mcp.recraft.ai/mcp`.
- **Midjourney:** no official API, and its terms reportedly forbid automation. **Keep it out of agent pipelines**; at most it's a human moodboard tool.

## Production patterns that work

- **Style lock before volume.**
  1. Hand-direct and approve 10–20 hero assets.
  2. Lock them as the style reference: a trained model (Scenario), a style ID (Recraft) or a reference-image set (Nano Banana, FLUX), from strongest to weakest.
  3. Generate the rest in batches against that lock.

  Write the lock into the brief so downstream agents can't drift.
- **Prompt seeds come in two parts:** a fixed *style block* that's identical across the whole set (medium, palette hexes, lighting, line weight, "no text, centered, flat background #00FF00 or transparent") plus a per-asset *subject line*. In handoff briefs, give the style block once and the subject line per asset row.
- **Self-checking loop.** Generate, preview/render, compare against the reference and the acceptance criteria (silhouette reads at the target size, palette clamped to brief hexes, clean alpha with no halo), then fix or regenerate. Agents with preview tools (VectorCraft, PhotoCraft, Blender, Godot MCP) can close this loop without the user.
- **Transparency:** prefer native alpha (gpt-image, Ideogram, Recraft). Otherwise generate on a flat chroma colour, remove the background, and check edges against both the light and dark game backgrounds.
- **Palette clamp:** run AI raster output through a palette-quantize step (PhotoCraft, Aseprite, or an in-engine shader) so generated assets obey the brief's palette exactly.
- **Size realism:** generate large, then downscale to @2x/@3x. Judge every asset at its in-game pixel size, not at generator resolution.
- **Prefer code-native assets where the style allows.** Shader effects, SVG drawn by Claude, procedural backgrounds and engine particles are free to iterate and never off-model. Mark them `[GENERATIVE]` or `[CODE]` in the inventory.

## Rights, disclosure, perception

These are three separate issues. Don't merge them, and cite each one for what it actually says.

- **App Store rules (guideline 5.2, Intellectual Property):** you must own or have the rights to use everything in the app and its store listing. That's satisfied by the generator's commercial-use terms plus no third-party IP in the output. It says **nothing about human authorship or AI disclosure**. As of Oct 2026, Apple doesn't require labelling AI-generated game art; re-check before advising. Reports of new Google Play and Steam disclosure rules are secondhand.
- **Copyright (a legal question, not an App Store rule):** in the US, purely AI-generated art probably isn't copyrightable, so others could copy it freely. If the user wants to protect the icon, mascot or key art as their own IP, those assets need **substantial human authorship**. That's the business reason for the human finishing pass, not an Apple requirement.
- **Vendor terms:** check each vendor's commercial-use terms before shipping (Scenario, Meshy, Ludo and others differ). Canva premium elements need a licence. Gemini output is watermarked.
- **Player perception:** backlash concentrates on assets that *look* AI-generated: generic rendering, inconsistent details, uncanny hands and text. Tight style locks, palette clamps and human finishing are the mitigation, and they also make the game look art-directed.
