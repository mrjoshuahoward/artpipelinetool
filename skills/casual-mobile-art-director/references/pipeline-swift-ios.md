# Native Swift / iOS Pipeline — Asset Production & Integration Notes

Working knowledge for advising on a native iOS art pipeline. Covers asset catalogs, SpriteKit (2D games), RealityKit (3D — SceneKit is deprecated), Metal, SwiftUI (UI-heavy games), Liquid Glass, and Icon Composer. Verified Nov 2026 against iOS 27 / Xcode 27; re-check version-specific claims if the date has moved on.

## Choosing the rendering layer

- **SwiftUI / UIKit only** — for UI-led casual games (word, trivia, narrative cards, idle-with-buttons, NYT Games-style). Asset catalogs do most of the work; animation via `withAnimation` / Core Animation.
- **SpriteKit** — Apple's 2D game framework. First-class for arcade, puzzle, runner, match-3. Built-in physics, particles, actions. Not deprecated (Apple still encourages it) but receives no new features — fine for casual 2D, just don't expect new APIs.
- **RealityKit** — Apple's recommended 3D framework on iOS now that **SceneKit is officially deprecated (OS 26)**. Use for 3D dioramas, isometric rooms, toy-like 3D. Existing SceneKit projects still run; new projects shouldn't start there (see WWDC25 session 288 for migration).
- **Metal** — only when the look genuinely requires custom shaders, post-processing, or you're building an engine. Don't reach for it without reason.
- **RealityKit / Reality Composer Pro** — if there's any AR angle.

Mixing is fine: SpriteKit scene hosted in a SwiftUI view via `SpriteView`, RealityKit via `RealityView`, Metal layers under SwiftUI, a Phaser/web game in a SwiftUI `WebView` (see `pipeline-phaser.md`). Most casual games are happiest in one primary layer with the others as accents.

## Asset catalogs — the foundation

Every native iOS game ships through `Assets.xcassets`. Set this up correctly or pay later.

- **Image sets** with @1x / @2x / @3x — provide all three for raster, or use a **single PDF or SVG** with "Preserve Vector Data" checked for resolution-independent UI art.
- **Image set appearances** — Any / Light / Dark variants. Casual games often skip dark mode; if you're skipping, set the image's appearance to "Any" only and document the choice. If you're supporting it, every UI illustration needs a dark variant — that's a real production cost.
- **Color sets** — define the palette here, reference by name in code. Lets you tweak the entire game's color from one place. Provide light/dark variants if supporting both.
- **Symbol images** — SF Symbols are free, customizable, and Apple-blessed. Use them for system-feel UI; resist them where the game's visual identity wants custom icons.
- **App icon** — now authored in **Icon Composer** as a layered `.icon` file (see *App icons* below), not a flat asset-catalog image set.

**Vector PDFs vs. SVG:** PDF has been Apple's preferred vector for years; SVG support arrived in Xcode 12 and is reliable now. Either works for UI icons; SVG is convenient when assets come from AI vector generators or Figma/Canva exports — but clean them first (outlined text, no embedded rasters, no filters).

## Typography

- **System fonts** (SF Pro, SF Pro Rounded, New York) are free, responsive to Dynamic Type, and feel native. For casual games that want a friendly feel, SF Pro Rounded is often enough.
- **Custom fonts** — drop `.ttf`/`.otf` in the bundle, list in `Info.plist` under `UIAppFonts`. Watch licensing — many display fonts are not licensed for app embedding.
- **Dynamic Type** — even casual games benefit from supporting accessibility text sizes for menus and dialogue. Game-world typography (score readouts) usually opts out.
- **Variable fonts** are well-supported and let you ship one file for many weights.

## SpriteKit-specific

- **Texture atlases** — Xcode packs a **Sprite Atlas** (`.spriteatlas`) inside the asset catalog, or a loose `.atlas` folder reference, at build time. Use one; don't ship loose textures. artpipeline's `derive` recipes place as `.spriteatlas`.
- **`SKAction` library** — define reusable actions once (`SKAction.scaleTo`, `.rotateByAngle`, `.sequence`, `.group`) and compose. Easing via `timingMode` (`.easeInEaseOut`, `.easeOut`) — basic but sufficient for most casual juice.
- **Custom easing** — `SKAction.customAction(withDuration:actionBlock:)` lets you implement spring/bounce curves not in the default set.
- **Shaders** — `SKShader` accepts GLSL-style fragment shaders. Same lexicon as Godot for palette swaps, outlines, etc. Apple's shader docs are thin; community examples carry you.
- **Particles** — `.sks` files edited in Xcode's particle editor. Visually friendly. The defaults are dated; spend time tuning.
- **Physics** — `SKPhysicsBody`. Excellent for puzzle and arcade. Categories + contact bitmasks are the trickiest concept.
- **Performance** — `SKView` shows FPS and node/draw counts in debug. Aim for 60fps on the lowest-supported device. Atlas aggressively; reuse `SKTexture` instances; avoid creating textures per-frame.

## RealityKit-specific (3D)

- **Asset format** — USDZ / USD is native. Blender exports USD directly; glTF → USDZ via Reality Converter. Reality Composer Pro for scene assembly and material graphs.
- **Stylized materials** — `UnlitMaterial` for flat/toon looks; Shader Graph materials (Reality Composer Pro) for toon ramps, rim light, palette swaps without writing Metal. Full PBR is often wrong for casual — say so in the brief.
- **Lighting** — directional + image-based lighting is the default; for a toy/diorama look, a soft IBL plus one key light reads well.
- **Animation** — bake in Blender, export USD; play via `AnimationResource`.
- **SceneKit legacy** — if the user has an existing SceneKit game, don't force a migration for art reasons alone; note the deprecation as a risk-register item.

## Metal — when and how

Reach for Metal when:
- The art direction depends on a custom post-process (CRT, painterly, riso) that SpriteKit/SceneKit shaders can't do cleanly.
- You're rendering huge particle counts or generative visuals.
- You're building an engine, not a game.

Otherwise: don't. The productivity cost is enormous.

If you do go Metal, `MetalKit` + a single render pipeline + a quad pass over a render target gets you most stylization needs.

## Liquid Glass (iOS 26+) — decide it deliberately

Apple's system design language since iOS 26. Glass is "a distinct functional layer for controls and navigation" above content. iOS 27 adds a user slider from ultraclear to fully tinted, so **you cannot predict glass translucency on a given device**.

- **APIs:** SwiftUI `glassEffect(_:in:)`, `GlassEffectContainer` (groups/morphs glass shapes, better perf), `.buttonStyle(.glass)` / `.glassProminent`, `ConcentricRectangle`, `backgroundExtensionEffect()`. UIKit: `UIGlassEffect`, `UIButton.Configuration.glass()` / `prominentGlass()`.
- **Opt-out is gone in practice:** `UIDesignRequiresCompatibility` was documented as temporary and is reported ignored on the iOS 27 SDK. Any standard SwiftUI/UIKit chrome (nav bars, sheets, tab bars, alerts) *will* be glass.
- **Art-direction decision every native brief must make:** (a) embrace glass for meta-UI (menus, settings, shop sheets) over gameplay, or (b) build fully custom game UI that doesn't use system controls, so the game's own material language rules. Mixed half-and-half usually looks unfinished.
- **Rules of thumb:** never on the playfield or on art; don't rely on glass translucency for legibility; test with Reduce Transparency, Reduce Motion, and both ends of the iOS 27 slider.
- **HIG game minimums:** 17pt default text (11pt minimum), 44×44pt default hit targets (28×28pt minimum), respect safe areas.

## App icons (Icon Composer)

- Source is a **layered `.icon` file** from Icon Composer (ships with Xcode; also standalone). Background layer + one or more foreground layers; the system adds specular highlights, refraction, shadow, blur.
- **Appearances:** default, dark, clear (light/dark), tinted (light/dark). The system derives any you don't supply — supply at least dark and check tinted/clear.
- **Canvas:** 1024×1024 unmasked square (system applies the mask — don't pre-mask). Layers: prefer vector (SVG/PDF, text outlined); PNG for painted art or mesh gradients. Crisp foreground edges, no feathering.
- **What it changes for art direction:** design the icon as 2–3 separable flat shapes; plan a single-color silhouette that survives clear/tinted modes; **drop baked gloss and drop shadows** (the system adds them). Painterly icons still work as a background layer but the hero shape should be clean.
- HIG: no "Play" text, no gameplay screenshots, simple shape, recognizable in every appearance.
- Godot and Capacitor builds: plan to finish the icon in Xcode with Icon Composer — don't rely on the engine's exporter producing a `.icon`.

## Color & lighting in Swift

- Define every color in the asset catalog by name, never as a literal in code.
- Use `UIColor(named:)` / `Color("name")` everywhere.
- For palette-driven art direction, structure the catalog as `Palette/Primary`, `Palette/Accent`, `Palette/Surface`, etc. — semantic names, not hex names.
- Display P3 wide-gamut colors are available; if a direction depends on a deep saturated red or green that sRGB can't quite reach, use a `.colorset` with Display P3 source values.

## Marketing & store assets

- **App Icon** — 1024×1024 layered source (see *App icons* above). Test it at 60×60 (home-screen size) and in tinted/clear modes very early. If the icon doesn't read at 60px in mono, the direction has a problem.
- **Screenshots** — check App Store Connect's current spec before finalizing. As of Nov 2026: iPhone 6.9" (1320×2868) is the recommended hero size; iPad 13" (2064×2752) required if the app runs on iPad; up to 10 per size, no alpha. Apple has announced additional required device classes for newer SDKs (e.g. iPhone Duo screenshots for iOS 27.1+ SDK builds from April 2027) — flag this in the risk register. Many casual games render screenshots as in-engine scenes with a debug "screenshot mode."
- **App Preview video** — optional but powerful. 15–30s, ≤30fps, up to 3 per size; plays before screenshots, so the first 3 seconds are the real thumbnail.
- **Game Center / Games app** — adopting Game Center gives visibility in Apple's Games app; achievements, Challenges, and Activities each need artwork. Add these to the asset inventory if Game Center is in scope.
- **Localization** — text in screenshots needs localized variants; bake the localization pipeline into the screenshot tool from day one.

## Performance targets

- 60fps as default; 120fps on ProMotion devices is achievable for SpriteKit/Metal but most casual games don't need it.
- Battery: long sessions on idle/cozy games matter. Avoid running shaders when the screen is static; use `SKView`'s `isPaused` or limit `preferredFramesPerSecond` for idle states.
- Thermals: sustained 3D rendering with heavy shaders will throttle within minutes on older iPhones. Test on a 2-year-old device.
- Cold launch: large initial texture loads cause splash-screen delays. Lazy-load by scene.
