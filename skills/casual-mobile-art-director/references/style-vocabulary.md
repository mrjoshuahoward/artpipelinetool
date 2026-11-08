# Style Vocabulary — Talk About Visuals Precisely

Use this when you find yourself reaching for vague terms. Vague art direction produces vague assets. Pick the specific word.

## Render style — say which one

- **Flat vector** — solid fills, hard edges, no gradients (or constrained gradients only). Inkscape/Affinity/Figma territory.
- **Vector-with-grain** — flat shapes plus a paper, film, or risograph texture pass. Indie-warm.
- **Painterly 2D** — visible brushwork, painted-edge variation. Procreate, Krita, Photoshop. Subdivides into:
  - **Gouache / picture-book** — opaque, matte, soft transitions
  - **Watercolor** — translucent washes, edge bleeds
  - **Oil-paint thick** — heavy impasto, rare on mobile due to scale
  - **Digital-painterly** — broad term; specify the brush feel
- **Line-and-flat** — drawn line with flat color fill underneath (Cozy Grove, A Little to the Left).
- **Hand-drawn line, no fill** — pure ink/pencil aesthetic.
- **Pixel art** — specify resolution tier: chunky (16×16 base), mid (32×32), HD pixel (64×64+). Specify palette restriction if any.
- **Lo-poly 3D, flat-shaded** — visible facets, no smooth shading (Crossy Road).
- **Lo-poly 3D, smooth-shaded** — facets present but Gouraud/Phong smoothing on (Alto's-adjacent).
- **3D-rendered-to-2D** — high-fidelity 3D rendered offline into sprite atlases (Royal Match, Gardenscapes). Read as 3D, ships as 2D, costs like 3D.
- **Real-time 3D, stylized shading** — toon shader, cel shader, painterly post-process.
- **Voxel** — cube-based 3D (Crossy Road's deeper cousin).
- **Mixed media / collage** — photo elements, scanned textures, layered.
- **Claymation / stop-motion** style — implied through soft imperfect forms and slight wobble.
- **Vector + 3D hybrid** — flat 2D characters in 3D environments, or vice versa.
- **Toy-block / chunky bevel** — thick bevelled, glossy-plastic blocks with soft shadows (Block Blast lineage). Reads physical and tappable at tiny sizes.
- **Vintage scientific illustration** — engraved line + muted watercolor plates, natural-history feel (Art of Fauna).

## Color register — specify the mood

- **Saturated / candy** — high chroma across the board (Candy Crush)
- **Muted / sophisticated** — desaturated, possibly with one saturated accent (Monument Valley)
- **Naturalistic** — real-world chroma, often warm-biased
- **Pastel** — high value, low saturation (Animal Crossing: Pocket Camp)
- **Dusk / dawn** — narrow palette around a single time-of-day (Alto's)
- **Monochrome+accent** — one hue family plus a single contrast color (Two Dots, Reigns)
- **Limited palette** — explicit count: "5-color palette," "risograph 3-color"
- **Tonal / value-led** — works in grayscale before color
- **Warm-cold split** — composition divided by temperature
- **Spot-color UI** — gameplay restrained, UI carries the chroma

## Lighting — even 2D has lighting decisions

- **Flat-lit** — no implied light direction
- **Single-key warm** — implied sun from one direction
- **Ambient + rim** — soft fill plus edge highlight (cozy default)
- **High-contrast directional** — strong shadows, dramatic
- **Glow / bloom-led** — light sources blow out softly (idle/magic games)
- **Day/night cycle** — palette shifts with state

## Motion personality — name the easing

- **Bouncy** — overshoot, settle. Cubic-out-back.
- **Snappy** — fast in, instant stop. Cubic-out.
- **Floaty** — slow accel and decel. Sine in-out.
- **Mechanical** — linear, no easing. Rare and deliberate.
- **Squashy** — squash-and-stretch on every interaction (Toon Blast, Royal Match)
- **Restrained** — minimal movement, dignified (Monument Valley, Mini Metro)

## Visual metaphor — what is it pretending to be?

A direction without a metaphor is decoration. Strong directions have a clear answer to "what object/medium/world is this game pretending to be?"

Examples of strong metaphors:
- A pop-up book (paper layers, fold creases)
- A diorama / shoebox theatre
- A scientific specimen drawer
- A weather map
- A cookbook
- A toy box
- A folk-art quilt
- A train-station departures board
- An old TV with CRT scanlines
- A field guide with marginalia
- A risograph zine
- A jeweler's loupe view
- A children's wooden toy set
- A botanical garden sign
- A souvenir snowglobe

The metaphor cascades into every other decision — typography, color, motion, sound, even haptics. If the direction doesn't have one, it's not done.

## UI material — what the controls are made of

- **System Liquid Glass** — Apple's translucent, refractive control layer (iOS 26+). Native chrome by default; user-adjustable translucency.
- **Tactile / soft-depth** — squishy, physically pressable buttons with real press states and soft shadows.
- **Flat chip** — solid flat shapes, no depth; relies on color and type.
- **Diegetic** — UI made of world objects (wooden signs, paper tags, game pieces).
- **Paper / print** — cards, stamps, torn edges; matches picture-book and risograph directions.

Pick one per game and say it in the brief. Mixed materials (glass menus over a paper-world game with flat HUD chips) is the most common way casual games look unfinished.

## Anti-vocabulary — terms to avoid or unpack

These are not bad words, but they hide the real decision:

- "Modern" — modern *what*? Swiss-grid? Memphis? Y2K? Brutalist?
- "Clean" — flat? minimalist? high-contrast? whitespace-heavy?
- "Cute" — round? small-headed? big-eyed? squishy? cartoon? plush-toy?
- "Stylized" — say which style.
- "Unique" — every direction must be unique; the word is empty.
- "Vibrant" — saturated? high-contrast? warm-biased? Pick.
- "Premium" — usually means muted palette + restrained motion + custom typography. Say that.
- "AI-style" / "like Midjourney" — names a generator, not a look. Unpack into medium, lighting, palette, and detail density.
- "Polished" — usually means consistent margins + intentional motion + considered type. Say that.
