# Production Loop — Making the Assets, Not Just Specifying Them

Read this when the user wants you to **produce the art yourself**: generate, draw, process, check and place real asset files, rather than write a brief for someone else. This file covers how to run the loop. `ai-production-tooling.md` covers which tool to use for each asset class.

The loop runs on **artpipeline**, the MCP server that ships in the same plugin as this skill. Its tools appear as `mcp__plugin_artpipeline_artpipeline__<tool>`. It stores state, attempts and provenance, processes and checks every file, renders contact sheets, and enforces the gates below so they hold across sessions and parallel subagents. You make the judgement calls; it keeps the record and refuses steps that skip a gate. Every refusal carries a `hint` naming the next valid step.

If the artpipeline tools are missing (`/mcp` doesn't list `plugin:artpipeline:artpipeline`), the same operations exist as a CLI: `artpipeline <command> --help`. If neither is available, tell the user the plugin isn't installed. Don't improvise the bookkeeping by hand.

## 0. Preconditions (settle these quickly, ask only what's missing)

| Need | Where it comes from | If missing |
|---|---|---|
| An approved direction | An art spec in the repo, a brief from this conversation, or the user's description | Run a short tightening pass first (pillars, palette, silhouette rules). Don't generate against a vague direction |
| The asset list | The brief's inventory, or the user's request | Draft the inventory and its `## Asset Manifest` (see `asset-manifest.md`). Confirm the **heroes** and the first batch |
| Where files go | The user's instruction or the repo layout | Ask once. **If the user says read-only, set the pipeline root to a separate output folder** and hand over install steps |
| Tools | Connected MCP tools, APIs, and local CLIs you can verify | Plan around what exists. Claude-authored SVG always works: artpipeline renders it |
| Budget | Paid generators bill per image or credit | Estimate the count before a large batch (e.g. "46 badges × ~3 attempts ≈ 140 generations") and get a yes |

Then call `init(brief_path, root)`. It is safe to re-run after editing the brief: progress is kept and changes are reported.

## 1. Style lock before volume

1. **Heroes first.** `claim` hands out only `hero: true` assets until the style is locked. Pick 2–4 that span the set's range.
2. Produce them (step 2), `register_attempt` each one, and look at the returned strips: true display sizes on the real backgrounds, plus a greyscale row.
3. **Sign-off gate:** show the user the hero strips (or `review_sheet` of the heroes; the full page paths are in `pages`) and the decisions they embody: palette, keyline, light direction, rendering. Approve each hero with `decide(..., by="user")` only for what the user actually approved.
4. `lock_style(by="user", style_block=..., palette=...)` only after the user says yes. The approved heroes become the references in every later work packet, and are shown inline when a worker claims.

**If the user is away and asked you to carry on** ("I'm away, do as many as you can"), make and check the heroes yourself, approve them with `by="agent"`, then `lock_style(by="agent", provisional=True)`. That opens non-hero work under a **provisional** lock:
- Batch gates are deferred: the user's real lock is the review. When they lock, every non-hero asset approved under the provisional lock goes back to review.
- Work packets, the manifest and `handback` all mark the work provisional. Open the hand-back with it: "the style is provisionally locked by me; nothing is final until you approve the hero sheet."
- Never lock provisionally when the user is present or reachable. Ask them instead. If they only said "just make them" without saying they're away, make the heroes and stop at the lock.

Re-locking later (a palette change, say) bumps the lock version and sends assets approved under the old lock back to review.

## 2. Choose the production route per asset

Prefer, in order (pick the first that can hit the style):

1. **Code-native:** an SVG you write directly, the engine's procedural drawing code, a shader, or particles. It's free, deterministic, always on-palette and easy to revise. Most flat, vector, geometric, icon, badge and UI work belongs here. If the game already draws its pieces in code (as many Phaser and Godot games do), **reuse that geometry** so store art and badges stay on-model. Register the SVG even for PNG classes; artpipeline renders it at the master size.
2. **Agent-driven app:** VectorCraft, PhotoCraft or EffectCraft MCP, the Blender connector, Figma or Canva. Use these when you need the app's operations (boolean ops, PSD layering, Lottie export, 3D renders, layout templates).
3. **Image generation:** painterly, illustrated, photographic or textural looks that code can't reach; volume after a style lock; hero drafts that a human will finish. Give it a real role when the style calls for it. Don't confine it to concepts out of caution. Use the work packet's `style.block` plus the asset's `subject`, and pass the lock's references to generators that take them.

Record the route honestly in `register_attempt` (`route`, `tool`, `model`, `prompt`, `seed`, `references`, `rights`). That provenance is what makes regeneration and rights questions answerable later.

## 3. Generate → check → fix (per asset)

```
claim(agent, n)                       → work packets: style lock, palette, sizes, criteria, earlier attempts + reasons
produce the file                      → code / app / generator (generate large; on a flat chroma colour if no native alpha)
register_attempt(asset_id, file, ...) → stored, processed (bg removal, trim, fit, flatten, palette clamp per the class),
                                        renditions exported, objectively checked
  checks fail  → you still hold it: fix the cause, register again with change_from_previous
  checks pass  → a strip at true display sizes comes back: look at it, then
decide(approve | reject, reason)      → rejected assets return to the queue with your reason in the next packet
```

- **Retry budget:** at most 3 attempts per asset (the brief's `max_attempts`). Each retry must change the *cause* (the subject line, a reference, a seed, the geometry) and say so in `change_from_previous`. Blind rerolls are refused. An exhausted asset is flagged for the user; move on.
- **Judge at display size, never at generation size.** The strips are built for that. Don't zoom into the master to approve.
- **Judge on the backgrounds the platform will use, not only the game's.** The presets already put Game Center and App Store art on iOS light and dark (`#F2F2F7`, `#1C1C1E`), and app icons get a rounded mask and a wallpaper tone. Dark-plate badges need a light rim or outer keyline to separate from dark mode.
- **What the objective checks cover** (failures block approval): size, the alpha rule (no alpha for App Store icons, screenshots and Game Center art; transparent corners for sprites), matte halos, palette share, and any processing refusal (no raster upscaling; integer factors for pixel art). Warnings (low contrast against a background, hue-only contrast that vanishes in greyscale) are yours to weigh on the strip.
- **The acceptance criteria are yours to judge.** Check each one against the strip before approving. Reject with the specific criterion that failed.
- Never AI-upscale pixel art. The `pixel_sprite` preset scales nearest-neighbour at integer factors only.

**Parallel workers.** For large sets, give each subagent its own `agent` label and have it `claim` its own batch. Leases keep two workers off the same asset. Decisions that need the user (`lock_style`, `pass_gate`, `unflag`) stay with the main conversation.

## 4. Human-finishing flags

Set `needs_human_finish: true` in the manifest for any asset where human authorship matters (app icon, mascot, key art). That isn't an App Store rule. It matters for copyright and IP protection, and for the "doesn't look generated" bar. `handback` lists these. Code-native and Claude-authored SVG assets don't need the flag for originality reasons, but they still need the user's taste sign-off at the gates.

## 5. Integrate and verify in the engine

The asset isn't done until it looks right **in the game**:

- **Staging is automatic.** On approval, artpipeline copies the processed master and its renditions to the asset's `destination` under the pipeline root (renditions sit beside it, e.g. `badge-512.png`). A file already there that the pipeline didn't write is moved to `superseded/<timestamp>/` first, never overwritten. `art-manifest.json` points at these copies (`approved.file`, `approved.renditions`). Don't copy files out of `.artpipeline/` by hand.
- **Place files** where the engine expects them: asset catalog image sets with `Contents.json`, Godot import presets, a Phaser atlas plus its preload-manifest entry, or the Icon Composer layer files for the app icon. Until artpipeline's engine placement tools land, copy from the staged files.
- **Pack atlases** (TexturePacker CLI, or the engine's own packer) when the set is final.
- **Screenshot in context:**
  - Phaser: the dev server plus Playwright on the real canvas.
  - Godot: the Godot MCP or a headless run.
  - Native: the iOS simulator.
- **Compare against the strips.** Watch for resolution softness (the DPR cap), wrong import filters, premultiplied-alpha fringes and colour-space shifts.
- **Read-only repo:** keep the pipeline root in a separate output folder, write `INSTALL.md` with exact copy steps and any config changes, and verify against a scratch copy or a branch the user owns. Never touch their working tree.
- **Don't overwrite existing art without confirmation.** Move superseded files to `superseded/` until the user approves.

## 6. Manifest

artpipeline writes `art-manifest.json` at the pipeline root after every decision. Each entry records the asset's status, the approved (staged) file and renditions, route, tool, model, prompt, seed, references, rights, check results, style-lock version and who approved it. Don't hand-write a manifest. If you need extra fields, put them in `rights` or `notes` on the attempt. `history(asset_id)` shows the full event log.

## 7. Review gates and hand-back

- **Gates:**
  - The style lock (step 1).
  - A **batch gate** every `gate_threshold` approvals (default 15). `decide` returns `gate_due`, and `claim` refuses until it passes. Build `review_sheet(gate_id=...)`, show the user (give them the `pages` paths), and call `pass_gate(by="user")` only after they sign off.
  - The in-engine screenshot (step 5).
- **Hand-back:** call `handback()`. It returns counts, flagged and unfinished assets, `needs_human_finish` items, the 3–5 likeliest taste-revision candidates (by attempts and warnings), the manifest path, and a final contact sheet. Add the in-engine screenshot. Revisions go through the same loop: claim, register a new attempt, decide. History is kept; nothing is forked.
