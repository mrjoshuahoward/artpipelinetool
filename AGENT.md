# artpipeline — Operating Guide for AI Agents

This document is the operating contract for an AI agent running the artpipeline production loop. Read it in full before issuing any commands.

---

## Before you start

**Verify `artpipeline` is on your PATH before doing anything else.**

```bash
artpipeline --help
```

If that fails, the tool was installed with `pip install -e .` from the artpipeline repo. Check where pip installed it:

```bash
pip show artpipeline   # look at "Location"; the script is in the adjacent Scripts/ or bin/ directory
```

**Windows fallback** — if PATH is not set up, the executable is at:

```
C:\Users\Joshu\AppData\Roaming\Python\Python314\Scripts\artpipeline.exe
```

Either add the Scripts directory to your PATH or use the full path for every command in this session.

---

**All commands after `parse` require your working directory to be the directory containing `pipeline.json`.** That is the same directory as the brief file. Change to it before running anything else and stay there for the entire session.

```bash
cd /path/to/project-directory
```

If any command returns `pipeline.json not found`, your working directory is wrong.

---

## Starting a run

```bash
artpipeline parse <brief.md>
```

Creates `pipeline.json` alongside the brief. Safe to re-run against an updated brief — existing asset statuses are preserved; new assets are added as `pending`.

**Output:**
```json
{
  "project": "Demo",
  "direction": "TestDir",
  "pipeline": "pipeline.json",
  "assets": [
    {"id": "bird_crane", "type": "bird_sprite", "status": "pending"}
  ]
}
```

---

## The production loop

Repeat until `next` returns `"asset_id": null`.

### 1. Get the next asset

```bash
artpipeline next
```

**Output — asset available:**
```json
{"asset_id": "bird_crane", "status": "pending", "next_command": "artpipeline prompt bird_crane"}
```

**Output — all done:**
```json
{"asset_id": null, "message": "All assets approved."}
```

When `asset_id` is `null`, the run is complete. Stop.

The `next_command` field tells you the exact command to run next. Use it.

---

### 2. Get the prompt

```bash
artpipeline prompt <asset_id>
```

Updates asset status to `prompted`. Returns the full image-gen prompt text.

**Output:**
```json
{
  "asset_id": "bird_crane",
  "prompt": "Top-down silhouette of a Sandhill Crane...",
  "retry_count": 0
}
```

Submit the value of `"prompt"` verbatim to the image generator in the browser. Do not paraphrase or modify it.

---

### 3. Generate and download the image

In the browser: paste the prompt into the image generator, wait for generation, download the result.

Note the download path — you will need it for the next step.

---

### 4. File the image

```bash
artpipeline file <downloaded-image-path> <asset_id>
```

Copies the image to its correct destination and updates status to `filed`.

**Output:**
```json
{"asset_id": "bird_crane", "filed_path": "art/birds/crane@1x.png"}
```

**If this fails:** Check that the source file exists at the path you provided, and that its extension matches the asset type (`.png` for `bird_sprite` and `app_icon`; `.svg` for `ui_glyph`). The command exits non-zero with a message on stderr.

---

### 5. Review the asset

```bash
artpipeline review <asset_id>
```

Runs programmatic checks and returns the acceptance criteria for your visual assessment.

**Output:**
```json
{
  "asset_id": "bird_crane",
  "checks": {
    "file_exists": true,
    "dimensions_correct": true,
    "has_alpha": true
  },
  "acceptance_criteria": [
    "Silhouette only, no internal detail",
    "Transparent background, no halo",
    "Bird oriented facing up (north)"
  ],
  "visual_review_required": true
}
```

**Programmatic check values:**
- `true` — check passed
- `false` — check failed
- `null` — Pillow not installed; check was skipped

**Decision rules for programmatic checks:**

| Check | `false` means | Action |
|---|---|---|
| `file_exists` | File wasn't saved correctly | Re-run `file` command |
| `dimensions_correct` | Wrong pixel dimensions | Reject — regenerate |
| `has_alpha` | No transparency (PNG assets only) | Reject — regenerate |

If any check is `false`, reject without proceeding to visual review.

If a check is `null` (skipped), proceed to visual review and assess that criterion yourself.

**Visual review:** Open the filed image. Evaluate each item in `acceptance_criteria` against what you see. If all criteria pass, approve. If any fail, reject with a specific reason.

---

### 6a. Approve

```bash
artpipeline approve <asset_id>
```

**Output:**
```json
{"asset_id": "bird_crane", "status": "approved"}
```

Return to step 1.

---

### 6b. Reject and retry

```bash
artpipeline reject <asset_id> --reason "<what specifically failed>"
```

The reason is stored and used in the retry prompt. Be specific — it becomes part of the next generation request.

**Output:**
```json
{"asset_id": "bird_crane", "status": "rejected", "retry_count": 1}
```

Then get a revised prompt:

```bash
artpipeline prompt <asset_id> --retry
```

The retry prompt prepends a revision instruction to the original prompt using the stored rejection reason:

```json
{
  "asset_id": "bird_crane",
  "prompt": "REVISION REQUEST: The previous attempt was rejected because: \"neck not visible at 1x scale\".\nPlease adjust accordingly.\n\nTop-down silhouette of a Sandhill Crane...",
  "retry_count": 1
}
```

Submit this prompt to the image generator and continue from step 3.

---

## Checking pipeline state

At any point you can inspect current state:

```bash
artpipeline status
```

Returns all assets grouped by status:
```json
{
  "pending": [{"id": "bird_crane", "type": "bird_sprite"}],
  "approved": [{"id": "ui_rotate", "type": "ui_glyph"}]
}
```

```bash
artpipeline status --asset <asset_id>
```

Returns the full record for one asset, including `rejection_reason`, `retry_count`, and `filed_path`.

---

## Batching by stage

If you want to process all assets of the same stage together (e.g., generate all prompts before opening the browser), use `--stage`:

```bash
artpipeline next --stage pending     # only pending assets
artpipeline next --stage filed       # only filed assets awaiting review
```

Valid stage values: `pending`, `prompted`, `filed`, `approved`, `rejected`.

---

## Error handling

All errors are written to stderr with a non-zero exit code. Stdout will be empty on failure. The error message describes what went wrong and what to fix.

Common errors and causes:

| Error | Cause |
|---|---|
| `pipeline.json not found` | Wrong working directory |
| `Asset '<id>' not found` | Typo in asset ID — run `status` to see valid IDs |
| `Source file not found` | Downloaded image path is wrong |
| `Wrong file extension` | File type doesn't match asset type |
| `must be filed before review` | Ran `review` before `file` |
| `--reason` is required | Ran `reject` without `--reason` flag |

---

## Output format

By default all commands output compact single-line JSON to stdout. This is the format to parse programmatically.

The `--human` flag switches to indented JSON. It is intended for development use only — do not rely on it in automated workflows.
