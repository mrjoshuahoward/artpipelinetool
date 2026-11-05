# Phaser Pipeline — Asset Production & iOS Shipping Notes

Working knowledge for advising on a Phaser game that ships to iPhone in a web-view wrapper, often alongside native Swift UI. Verified November 2026. Check the versions below before quoting them; Phaser 4 is still moving fast.

## Version reality

- **Phaser 4 is current.** 4.0 shipped April 2026 and 4.2.x was out by mid-2026. **Phaser 3** froze at 3.90. Many existing projects are still on v3, so ask which one before giving API-level advice: the art-relevant APIs changed a lot.
- **Changes in v4 that affect art direction:**
  - **Filters replace preFX, postFX and BitmapMask.** One Filter system works on any game object or camera. It covers Blur, Glow, Shadow, Pixelate, ColorMatrix, Bloom, Vignette, Wipe, GradientMap, Quantize, Blend, Mask and ImageLight.
  - **Lighting is per object** via `setLighting(true)`, replacing the Light2D pipeline. It works on sprites, text, BitmapText, Graphics, particles and tilemaps, and adds self-shadowing and light height. **Lighting breaks batching**, so budget for it.
  - **Six tint modes** via `setTintMode`: MULTIPLY, FILL, ADD, SCREEN, OVERLAY and HARD_LIGHT. 4.2 adds a second tint colour (`setTint2`), which makes palette and cosmetic variants cheap.
  - **`roundPixels` now defaults to false.** Pixel-art games must turn it back on.
  - **New objects:** Gradient, Noise, Mesh2D, Stencil and Stamp. **SpriteGPULayer** and **TilemapGPULayer** draw huge counts in one call.
  - **Removed:** 3D Mesh, Plane and Camera3D. The Canvas renderer is deprecated; WebGL is the target.
  - **Shaders** use a config-based API. Custom v3 pipelines must be rewritten as render nodes.
- **Official AI tooling:**
  - **Phaser Editor v5** bundles an MCP server (still marked "under development") that edits scenes, assets and tilemaps and takes screenshots through a running editor.
  - The `phaser` npm package ships agent skills (loading-assets, filters-and-postfx, particles, scale-and-responsive, v3-to-v4-migration, and more).
  - In Claude Code, prefer these over guessing at the API.

## Asset formats

| Need | Phaser approach | Art-direction note |
|---|---|---|
| Sprites and UI | `load.atlas` (one page) or `load.multiatlas` (several PNG pages, one JSON) | Pack per scene. Keep pages at 2048–4096, even though iOS reports 8–16k max |
| Fixed-grid animation | `load.spritesheet` with frame size, margin and spacing | Suits AI-generated or Aseprite strips |
| 9-slice panels | Native `NineSlice`; reads slice data from TexturePacker 7.1+ JSON | Author panels once and scale them freely |
| Bitmap fonts | `load.bitmapFont` (BMFont, Glyph Designer or Littera output) | Use for score readouts and display type; crisp, tintable and lit in v4 |
| Web fonts | Bundle the files locally. Wait on `document.fonts.load()` before creating Text | Otherwise fallback glyphs get baked into the text texture |
| SVG | `load.svg(key, url, {width, height})` rasterizes at load time | Set the size for the target density, not the source size |
| Compressed textures | `load.texture` with a PVR/KTX container per format; ASTC (UNorm) first for iOS | v4 needs the Y axis flipped on re-export. Big memory win for large backgrounds |
| Skeletal animation | Official `spine-phaser-v4` runtime (needs Phaser 4.2.1+); batches with sprites via Mesh2D | The rigged-character path |
| Rive / Lottie | No official plugin. Render to an offscreen canvas, then `textures.addCanvas` and refresh it every frame | Costly; keep it to menus and onboarding, not gameplay |
| Particles | `this.add.particles()` returns an emitter, with zones, `advance` and `fastForward`; lit in v4 | Cap counts and provide a low-FX setting |

## Resolution & scaling

- **Logical size:** use a fixed logical game size with `scale.mode` FIT (letterbox) or ENVELOP (crop), plus `autoCenter`. Design safe-zone art for the crop.
- **Device pixel ratio:** a full DPR 3 backing canvas costs 9× the fill and memory of DPR 1. **Cap the effective DPR at about 2 and author art at @2x.** On a phone, @3x rarely shows a visible difference in a game canvas. This is a recommendation, not a Phaser rule. Check how v4's GameConfig handles resolution, because v3 community reports are inconsistent.
- **Texture memory:** an uncompressed 4096² RGBA page is 64 MB. Destroy textures for scenes you leave.

## Shipping to iOS

- **Wrapper:**
  - **Capacitor 8** is current: iOS 15+, Xcode 26, Swift Package Manager by default. Capacitor 9 is expected around the end of 2026.
  - **Cordova** is legacy; don't start new projects on it.
  - A **bare WKWebView**, or the SwiftUI `WebView` on iOS 26+, also works.
- **Safe areas:** set `viewport-fit=cover` and use the `env(safe-area-inset-*)` and SystemBars CSS variables. Don't also set `ios.contentInset: 'always'`, or the insets get applied twice. Gameplay art needs to extend into the unsafe areas; HUD elements stay inside them.
- **Launch screen, the native-to-web handoff:** `LaunchScreen.storyboard` (static, no text) is shown by iOS, then the WKWebView paints `index.html`, then Phaser boots and draws its first scene. Each layer can show a different background, so the art direction must make them **one continuous image**:
  - Use the same background colour in the storyboard (a named colour, not `systemBackgroundColor`, which turns white in light mode), in `capacitor.config.ts` `backgroundColor`, in `index.html`'s body, and in Phaser's `backgroundColor`.
  - Put the same centred mark on the native launch screen and as an inline SVG in `index.html`.
  - Use `@capacitor/splash-screen` and call `SplashScreen.hide()` once Phaser's first scene is ready.
  - Avoid aspect-fill on a square launch image: on a portrait iPhone it crops to roughly the middle half.
  - Audit these four places whenever a brief touches the launch screen.
- **App icon:** see `pipeline-swift-ios.md`. Icon Composer and the layered `.icon` format apply to Capacitor apps too.
- **Haptics:** `@capacitor/haptics` provides impact (light/medium/heavy), notification (success/warning/error) and selection. Haptics belong in the motion-personality spec, so pair them with juice moments.
- **Frame rate:** WKWebView caps `requestAnimationFrame` at about 60fps on ProMotion devices; unlocking it needs private API, which risks App Store rejection. **Low Power Mode throttles it to about 30fps.** Animate with delta time and review the game's juice at 30fps.

## Hybrid (native shell + Phaser canvas)

- **Hosting:** put the game in a SwiftUI `WebView`/`WebPage` (iOS 26+) or a WKWebView in `UIViewRepresentable`. Native SwiftUI handles the store, settings, Game Center and ads as overlays.
- **Bridge:**
  - JS to native: `window.webkit.messageHandlers.X.postMessage`.
  - Native to JS: `evaluateJavaScript`/`callJavaScript`.
  - Under Capacitor, write a small local plugin instead.
- **Pause the game behind modals:** call `game.loop.sleep()` while native modals are up, for battery and heat.
- **One visual system across both sides:**
  - Shared colour tokens: generate the asset-catalog colorsets and a JS/CSS token file from one source.
  - The same font files bundled on both sides.
  - Matched easing curves.
  - This seam is where hybrid games look cheap. Call it out in briefs, and decide whether native UI adopts Liquid Glass or matches the game's own material.

## DOM UI over the Phaser canvas (the in-web seam)

Many Phaser games, Sorting Line-style, draw the board in the canvas and the menus or meta screens as HTML/CSS over it or beside it. This is a **second visual seam**, separate from native vs. web, and it belongs in the **risk register** of any brief that touches either surface.

- **The two surfaces render differently:**
  - Phaser Text rasterizes into a texture, while DOM text stays live and sharp.
  - CSS gradients and filters don't match Phaser filters.
  - Canvas colours can shift with the DPR cap or with tint and lighting.
  - Easing in CSS transitions and in Phaser tweens drifts apart unless both use the same curves.
- **Make one source of truth.** A single token module (colours, radii, font stacks, easing curves and durations) exported to Phaser as numbers and to CSS as custom properties. Then a test that both sides read from it.
- **Fonts:** load web fonts once, and wait on `document.fonts` before creating any Phaser Text, so both surfaces show the same glyphs.
- **Transitions between the board and the meta screens** are where the seam shows. Spec them explicitly: what fades, what is shared, and whether the canvas sleeps behind the DOM.

## Performance gotchas (WKWebView)

- **WebContent memory has no fixed limit; it depends on device RAM.** Going over it kills the web process (`webViewWebContentProcessDidTerminate`), so reload and restore state in that callback. Prefer ASTC and per-scene atlases.
- **WebGL context loss:** happens on texture-heavy scene switches. Listen for `webglcontextlost`. Turning off antialiasing has helped on some iOS versions.
- **Thermal throttling:** full-screen Bloom, Blur and lighting filters cost the most. Bake glow into art where possible, and keep live filters for moments rather than as ambient effects.
- **Draw calls:** use per-scene atlases and SpriteGPULayer/TilemapGPULayer for dense layers. Each lit object or filtered object adds batch breaks.

## Handoff-brief templates for Phaser

In a handoff brief, include:
- The atlas JSON shape (TexturePacker "Phaser 3" hash or multiatlas output).
- A preload manifest: an asset key → file → loader table.
- The `capacitor.config.ts` stanzas that affect visuals (backgroundColor, SplashScreen, SystemBars).
- A shared design-token file.
