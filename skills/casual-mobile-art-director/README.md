# casual-mobile-art-director

The art-direction half of the **artpipeline** plugin (see the repository README for install). It acts as an **art director and art producer for casual mobile games** built in native Swift/iOS, Godot or Phaser (shipped to iPhone through Capacitor).

## Modes

| Mode | Use it when | What you get |
|---|---|---|
| **Ideation** | You have a mechanic or pitch but no look yet | 3 genuinely different directions, each with a metaphor, precedent, risk, pipeline line and moodboard |
| **Tightening** | You already know the direction | Contradictions and risks surfaced, questions asked in batches, then a brief. No alternatives |
| **Deep-dive** | A direction is chosen; write it up | A discussion brief, or a handoff brief (with a `## Asset Manifest`) another agent can execute |
| **Production** | You want the actual files | Run through the artpipeline MCP tools: hero style lock, generate → check → fix, review gates, manifest, hand-back |

## Layout

```
SKILL.md                     modes, flows, behaviour rules
references/
  production-loop.md         how production runs on the artpipeline tools
  asset-manifest.md          the ## Asset Manifest schema (artpipeline v2) and built-in classes
  ai-production-tooling.md   agent-drivable tools, asset-class → tool routing, style-lock patterns, rights
  pipeline-phaser.md         Phaser 3/4, atlases, Capacitor/WKWebView, DOM-over-canvas seam
  pipeline-swift-ios.md      asset catalogs, SpriteKit/RealityKit, Liquid Glass, Icon Composer, store specs
  pipeline-godot.md          Godot 4.4–4.7 import, shaders, iOS export, MCP
  casual-mobile-canon.md     touchstone titles and current trends (dated; verify with web search)
  style-vocabulary.md        precise words for render style, colour, lighting, motion, UI material
```

The Pillow scripts this skill used to bundle (check, clamp, export, contact sheet) were replaced by artpipeline in Nov 2026.

## Evals

The plugin's evals use the in-development game **Sorting Line** (private; copied read-only into each run from a local clone, pinned to one commit) as the test subject:

- `icon-directions-greenfield`
- `meta-screens-tightening`
- `store-assets-handoff`
- `achievement-badges-production`

They live at the plugin root, `evals/`, because they test the skill and the MCP server together. See the repository README for how to run them (these are real, billed model runs).

## History

- **2026-11 (v2):** moved into the artpipeline repo as part of the plugin. Production runs on the artpipeline MCP tools, and handoff briefs carry a v2 `## Asset Manifest`.
- **2026-11:** a major update: production mode, the AI tooling reference, Phaser, iOS 27 and Liquid Glass, Godot 4.7. Evals went from 63% to 100% against the May version.
- **2026-05:** first version, for claude.ai.
