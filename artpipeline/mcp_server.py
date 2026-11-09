"""MCP server: the primary interface in Claude Code.

Every tool returns structured content (the same JSON the CLI prints) plus a text copy. Review
tools also return images: one strip per asset at true display sizes, so the model judges art the
way the player will see it. Refusals come back as is_error results carrying the stable error code
and a hint naming the next valid step."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.utilities.types import Image as McpImage
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from PIL import Image
from pydantic import BaseModel, Field

from artpipeline import __version__
from artpipeline.errors import PipelineError
from artpipeline.pipeline import Pipeline
from artpipeline.store import Store

# Images whose long edge exceeds this are scaled down by the client before the model sees them,
# which would make "true display size" tiles lie. Strips are built to stay under it.
MAX_INLINE_EDGE = 1568
MAX_INLINE_IMAGES = 16
REF_THUMB = 384

INSTRUCTIONS = """artpipeline tracks and enforces a game-art production run. Typical loop:
1. init(brief) once. Heroes come first: claim → produce → register_attempt → look at the returned
   strip at display size → decide. Show the user the hero strips; only after they approve call
   lock_style(by="user"). If the user is away and told you to carry on, you may instead call
   lock_style(by="agent", provisional=true) once the heroes pass: work continues, gates are deferred,
   and everything stays provisional until the user locks (say so in the hand-back).
2. Then claim(n, agent) per worker (subagents use their own agent label). Each work packet carries the
   style lock, palette, references (shown inline), and every earlier attempt's failure or rejection
   reason. Produce with the right tool (code-drawn SVG, connected generator/app), then
   register_attempt with honest provenance. Failed checks keep the asset with you: fix the cause and
   register again with change_from_previous. Retries are capped; exhausted assets get flagged.
3. When decide() returns gate_due, stop claiming: review_sheet(gate_id), show the user, and call
   pass_gate(by="user") only after they sign off.
   Approved files are copied to their destination under the root automatically (anything already
   there is moved to superseded/, never overwritten); art-manifest.json points at those copies.
For sets larger than a handful, use register_attempts and decide_batch (one call per batch, one
grid view of everything that passed) and check_image(asset_id=...) to pre-check drafts for free.
Assets with a `build:` recipe in the brief are built by artpipeline itself: write or edit the recipe
files (SVG with {{tokens.name}} colours, <ap:slot/> templates, <ap:star>/<ap:gear>/... shapes,
<ap:text font=...> drawn from a committed font; or kind: compose layer stacks for store screenshots and
key art, which can layer other approved assets; or kind: derive to pack approved frames into a sprite
sheet or texture atlas, which place() writes as engine atlas data; or, when none of those fits, kind: script,
a committed program run with only its declared inputs), then
build(asset_ids | group) — it claims, compiles, registers and checks in one call (dry_run=true to
iterate for free). After a recipe, template or token change, build(stale=true) rebuilds every
affected asset for review (including compose/derive assets whose layer or frame was re-approved). Don't write
throwaway generator scripts: put the drawing in a recipe, or commit the script as a kind: script recipe.
4. place(target=...) writes approved art into the game project (xcassets, godot, phaser) only when
   the user asks for it; a read-only or unknown project gets target="staging" (ART-INSTALL.md).
5. handback() at the end. by="user" means the user said so in this conversation; never set it on
   your own judgement."""

server = MCPServer(name="artpipeline", version=__version__, instructions=INSTRUCTIONS)
_root: Path | None = None

RO = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
RW = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)

By = Annotated[Literal["user", "agent"], Field(
    description="'user' only when the user explicitly decided this in the conversation; otherwise 'agent'.")]
UserOnly = Annotated[Literal["user"], Field(
    description="Must be 'user': call only after the user has explicitly signed off in the conversation.")]
Agent = Annotated[str, Field(description="Your worker label, e.g. 'main' or 'sub-2'. Keep it stable.")]


# ---------------------------------------------------------------- plumbing

def _pipeline() -> Pipeline:
    if _root is not None:
        return Pipeline(Store.open(_root))
    env = os.environ.get("ARTPIPELINE_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR")
    return Pipeline(Store.discover(Path(env) if env else None))


def _result(data: Any, images: list[Path] | None = None, notes: list[str] | None = None) -> CallToolResult:
    blocks: list[Any] = [TextContent(type="text", text=json.dumps(data, indent=1))]
    for note in notes or []:
        blocks.append(TextContent(type="text", text=note))
    for p in (images or [])[:MAX_INLINE_IMAGES]:
        blocks.append(McpImage(path=p).to_image_content())
    structured = data if isinstance(data, dict) else {"results": data}
    return CallToolResult(content=blocks, structured_content=structured)


def _error(e: PipelineError) -> CallToolResult:
    d = e.to_dict()
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(d, indent=1))],
                          structured_content=d, is_error=True)


def _call(fn, *args, **kwargs) -> CallToolResult:
    try:
        return fn(*args, **kwargs)
    except PipelineError as e:
        return _error(e)


def _strip_images(sheet: dict[str, Any]) -> tuple[list[Path], list[str]]:
    paths = [Path(p) for p in sheet.get("strips", {}).values()]
    notes = []
    for p in paths:
        with Image.open(p) as im:
            if max(im.size) > MAX_INLINE_EDGE:
                notes.append(f"{p.name} is {im.size[0]}x{im.size[1]}: the client will downscale it, so "
                             "tiles are not at true size. Open the file to judge exact sizes.")
    if len(paths) > MAX_INLINE_IMAGES:
        notes.append(f"Showing {MAX_INLINE_IMAGES} of {len(paths)} strips inline; the rest are in 'strips'.")
    return paths, notes


GRID_AUTO = 6  # more assets than this: show the compact grid inline instead of one strip each


def _review_images(sheet: dict[str, Any], layout: str) -> tuple[list[Path], list[str]]:
    n = len(sheet.get("strips", {}))
    if layout == "grid" or (layout == "auto" and n > GRID_AUTO):
        paths = [Path(p) for p in sheet.get("grid", [])]
        notes = [f"Grid: {n} asset(s) at their smallest display size, colour then greyscale, on each review "
                 "background, unscaled. Per-asset strips at every display size are in 'strips'; open one "
                 "(or call review_sheet(asset_ids=[...], layout='strips')) for anything you're unsure of."]
        if len(paths) > MAX_INLINE_IMAGES:
            notes.append(f"Showing {MAX_INLINE_IMAGES} of {len(paths)} grid pages inline.")
        return paths, notes
    return _strip_images(sheet)


def _thumbs(paths: list[str], root: Path) -> list[Path]:
    out = []
    for rel in paths[:4]:
        src = (root / rel) if not Path(rel).is_absolute() else Path(rel)
        if not src.is_file() or src.suffix.lower() == ".svg":
            continue
        thumb = root / ".artpipeline" / "thumbs" / (src.stem + "-ref.png")
        if not thumb.exists():
            thumb.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(src) as im:
                im.thumbnail((REF_THUMB, REF_THUMB))
                im.save(thumb)
        out.append(thumb)
    return out


# ---------------------------------------------------------------- tools

@server.tool(annotations=RW)
def init(brief_path: Annotated[str, Field(description="Markdown brief with '## Asset Manifest' (version: 2) or a YAML file")],
         root: Annotated[str | None, Field(description="Project/output folder; default: the brief's folder")] = None,
         ) -> CallToolResult:
    """Create or refresh the pipeline from a brief. Safe to re-run: progress is kept, changes are reported."""
    def go():
        global _root
        p, report = Pipeline.init(Path(brief_path).expanduser(), Path(root).expanduser() if root else None)
        _root = p.root
        return _result(report)
    return _call(go)


@server.tool(annotations=RW)
def open_pipeline(root: Annotated[str, Field(description="Folder that contains .artpipeline/")]) -> CallToolResult:
    """Point this session at an existing pipeline (otherwise it is found from the project folder)."""
    def go():
        global _root
        _root = Store.open(Path(root).expanduser()).root
        return _result(_pipeline().status())
    return _call(go)


@server.tool(annotations=RO)
def status(asset_id: str | None = None) -> CallToolResult:
    """Counts by state, style lock, open gate, leases; or one asset's full record and attempts."""
    return _call(lambda: _result(_pipeline().status(asset_id)))


@server.tool(annotations=RW)
def claim(agent: Agent,
          n: Annotated[int, Field(ge=1, le=20)] = 1,
          group: str | None = None,
          asset_ids: list[str] | None = None,
          show_references: bool = True) -> CallToolResult:
    """Lease up to n assets and get their work packets (style lock, palette, sizes, criteria, earlier
    attempts and why they failed). Naming asset_ids you already hold renews the lease. Locked
    reference images are shown inline when show_references is true."""
    def go():
        p = _pipeline()
        out = p.claim(agent, n, group=group, asset_ids=asset_ids)
        imgs: list[Path] = []
        if show_references and out["claimed"]:
            style = out["claimed"][0]["style"]
            imgs = _thumbs(style.get("references") or [], p.root)
        return _result(out, imgs)
    return _call(go)


@server.tool(annotations=RW)
def release(asset_id: str, agent: Agent) -> CallToolResult:
    """Give a claimed asset back to the queue."""
    return _call(lambda: _result(_pipeline().release(asset_id, agent)))


@server.tool(annotations=RW)
def register_attempt(
    asset_id: str,
    file: Annotated[str, Field(description="Path to the produced file (PNG/WebP/JPG, or SVG)")],
    agent: Agent,
    route: Literal["code_native", "agent_app", "image_gen", "human"],
    tool: Annotated[str, Field(description="What produced it, e.g. 'Claude SVG', 'gpt-image-2', 'VectorCraft'")],
    model: str | None = None,
    prompt: str | None = None,
    seed: str | None = None,
    references: list[str] | None = None,
    rights: str | None = None,
    notes: str | None = None,
    change_from_previous: Annotated[str | None, Field(
        description="Required from the 2nd attempt: what you changed about the cause (not a blind reroll)")] = None,
    preview: Annotated[bool, Field(description="Return the asset at display sizes inline (counts as review)")] = True,
) -> CallToolResult:
    """Register an attempt: the file is stored, processed into the class master and renditions, and
    checked. Passing attempts come back with a strip at true display sizes on the review
    backgrounds (plus greyscale); look at it before decide()."""
    def go():
        p = _pipeline()
        prov = {"route": route, "tool": tool, "model": model, "prompt": prompt, "seed": seed,
                "references": references or [], "rights": rights, "notes": notes}
        out = p.register_attempt(asset_id, file, agent, prov, change_from_previous)
        imgs, notes_ = [], []
        if preview and out["status"] == "awaiting_review":
            sheet = p.review_sheet([asset_id], actor=agent)
            out["sheet_id"] = sheet["sheet_id"]
            out["next"] = "Judge the strip at its true sizes, then decide(approve|reject)."
            imgs, notes_ = _strip_images(sheet)
        return _result(out, imgs, notes_)
    return _call(go)


Layout = Annotated[Literal["auto", "grid", "strips"], Field(
    description="Inline view: 'strips' = one image per asset at every display size; 'grid' = many assets "
    "per image at the smallest display size; 'auto' = grid when more than 6 assets")]


@server.tool(annotations=RW)
def review_sheet(asset_ids: list[str] | None = None,
                 pending_review: bool = False,
                 gate_id: int | None = None,
                 layout: Layout = "auto") -> CallToolResult:
    """Contact sheet of the latest attempts, shown inline at true size; full pages are saved for the
    user (paths in 'pages'). Marks those attempts as reviewed."""
    def go():
        sheet = _pipeline().review_sheet(asset_ids, pending_review=pending_review, gate_id=gate_id)
        imgs, notes_ = _review_images(sheet, layout)
        return _result(sheet, imgs, notes_)
    return _call(go)


class AttemptItem(BaseModel):
    asset_id: str
    file: str
    change_from_previous: str | None = None
    prompt: str | None = None
    seed: str | None = None
    notes: str | None = None


@server.tool(annotations=RW)
def register_attempts(
    attempts: Annotated[list[AttemptItem], Field(description="One entry per asset you hold a lease on")],
    agent: Agent,
    route: Literal["code_native", "agent_app", "image_gen", "human"],
    tool: Annotated[str, Field(description="What produced them, e.g. 'Claude SVG', 'gpt-image-2'")],
    model: str | None = None,
    references: list[str] | None = None,
    rights: str | None = None,
    preview: Annotated[bool, Field(description="Show the passing ones inline (counts as review)")] = True,
    layout: Layout = "auto",
) -> CallToolResult:
    """register_attempt for a batch that shares one route/tool: each file is stored, processed and
    checked. Returns a compact result per asset plus one review view of all that passed."""
    def go():
        p = _pipeline()
        results, passing = [], []
        for a in attempts:
            prov = {"route": route, "tool": tool, "model": model, "prompt": a.prompt, "seed": a.seed,
                    "references": references or [], "rights": rights, "notes": a.notes}
            try:
                out = p.register_attempt(a.asset_id, a.file, agent, prov, a.change_from_previous)
            except PipelineError as e:
                results.append({"asset_id": a.asset_id, "error": e.code, "message": e.message, "hint": e.hint})
                continue
            chk = out["checks"]
            results.append({"asset_id": a.asset_id, "attempt": out["attempt"], "status": out["status"],
                            "fail": chk.get("fail", []), "warn": chk.get("warn", []),
                            "attempts_left": out["attempts_left"]})
            if out["status"] == "awaiting_review":
                passing.append(a.asset_id)
        data: dict[str, Any] = {"results": results, "counts": {}}
        for r in results:
            k = r.get("status") or "error"
            data["counts"][k] = data["counts"].get(k, 0) + 1
        imgs, notes_ = [], []
        if preview and passing:
            sheet = p.review_sheet(passing, actor=agent)
            data["sheet_id"], data["pages"] = sheet["sheet_id"], sheet["pages"]
            imgs, notes_ = _review_images(sheet, layout)
            data["next"] = ("Judge the passing assets on the inline view, then decide_batch. Fix failures "
                            "and register again with change_from_previous.")
        return _result(data, imgs, notes_)
    return _call(go)


@server.tool(annotations=RW)
def build(
    agent: Agent,
    asset_ids: Annotated[list[str] | None, Field(description="Assets to build (each needs a build: recipe)")] = None,
    group: Annotated[str | None, Field(description="Build every buildable asset in this group")] = None,
    stale: Annotated[bool, Field(description="Only assets whose recipe output changed since their last "
                                 "build (edited source/template/include/font/script input, layers, params, token colours, or a re-approved "
                                 "layer, frame or script asset)")] = False,
    change_from_previous: Annotated[str | None, Field(
        description="Required when rebuilding after a rejection or failed checks: what you changed and why. "
        "The recipe diff is appended automatically")] = None,
    changes: Annotated[dict[str, str] | None, Field(
        description="Per-asset change_from_previous, keyed by asset id (overrides the shared one)")] = None,
    rights: str | None = None,
    notes: str | None = None,
    dry_run: Annotated[bool, Field(description="Compile and check without using an attempt or changing "
                                   "state; returns a strip per asset (not a review)")] = False,
    preview: Annotated[bool, Field(description="Show the passing ones inline (counts as review)")] = True,
    layout: Layout = "auto",
) -> CallToolResult:
    """Build assets from their recipes: artpipeline compiles each recipe (svg, compose and derive in
    process; script by running the committed script with only its declared inputs), using named colours
    from the style lock, claims or reopens the asset, registers the result as an attempt with the recipe
    as provenance, processes and checks it. Recipes are committed files, so the set can be rebuilt any
    time; a rebuild that would produce the same file is refused, and a script that writes the same file
    again just refreshes its record."""
    def go():
        p = _pipeline()
        out = p.build(agent, asset_ids, group=group, stale=stale, change_from_previous=change_from_previous,
                      changes=changes, rights=rights, notes=notes, dry_run=dry_run)
        imgs, notes_ = [], []
        if dry_run:
            imgs = [Path(r["strip"]) for r in out["results"] if r.get("strip")]
            if len(imgs) > MAX_INLINE_IMAGES:
                notes_.append(f"Showing {MAX_INLINE_IMAGES} of {len(imgs)} dry-run strips inline.")
        elif preview and out.get("passing"):
            sheet = p.review_sheet(out["passing"], actor=agent)
            out["sheet_id"], out["pages"] = sheet["sheet_id"], sheet["pages"]
            imgs, notes_ = _review_images(sheet, layout)
            out["next"] = ("Judge the passing assets on the inline view, then decide_batch. For failures, fix "
                           "the recipe and build again with change_from_previous.")
        return _result(out, imgs, notes_)
    return _call(go)


@server.tool(annotations=RW)
def decide(asset_id: str, decision: Literal["approve", "reject"], by: By,
           reason: Annotated[str | None, Field(description="Required to reject: what specifically failed")] = None,
           ) -> CallToolResult:
    """Approve or reject the asset's current attempt (it must have been on a sheet or preview)."""
    return _call(lambda: _result(_pipeline().decide(asset_id, decision, by, reason)))


class DecisionItem(BaseModel):
    asset_id: str
    decision: Literal["approve", "reject"]
    reason: str | None = None


@server.tool(annotations=RW)
def decide_batch(decisions: Annotated[list[DecisionItem], Field(
                     description="Rejections need a specific reason each")],
                 by: By) -> CallToolResult:
    """decide() for several assets at once (each must have been on a sheet or preview). A refusal is
    reported for that asset; the rest still go through."""
    return _call(lambda: _result(_pipeline().decide_batch([d.model_dump() for d in decisions], by)))


@server.tool(annotations=RW)
def lock_style(by: Annotated[Literal["user", "agent"], Field(
                   description="'user' only after the user approved the heroes in this conversation. "
                   "'agent' is allowed only with provisional=true.")],
               style_block: Annotated[str | None, Field(description="Default: the brief's style block")] = None,
               palette: list[str] | None = None,
               tokens: Annotated[dict[str, str] | None, Field(
                   description="Named colours for recipes, e.g. {'gold': '#F2C14E'}. Default: the previous "
                   "lock's, else the brief's. Without palette, the palette is these colours")] = None,
               hero_ids: list[str] | None = None,
               references: list[str] | None = None,
               notes: str | None = None,
               provisional: Annotated[bool, Field(
                   description="Only when the user is away and asked you to carry on: by='agent' locks "
                   "provisionally so non-hero work can continue. Nothing approved under it is final; the "
                   "user's real lock sends it back to review. Never use it to skip a user who is present.")]
               = False) -> CallToolResult:
    """Lock the style after the user approves the heroes. Non-hero work opens; every later work
    packet carries this lock. Re-locking sends assets approved under the old lock back to review."""
    return _call(lambda: _result(_pipeline().lock_style(
        by, style_block, palette=palette, hero_ids=hero_ids, references=references, notes=notes,
        provisional=provisional, tokens=tokens)))


@server.tool(annotations=RW)
def pass_gate(gate_id: int, by: UserOnly, notes: str | None = None) -> CallToolResult:
    """Record the user's sign-off on a batch review gate (after they have seen its sheet)."""
    return _call(lambda: _result(_pipeline().pass_gate(gate_id, by, notes)))


@server.tool(annotations=RW)
def flag(asset_id: str, reason: str, by: By) -> CallToolResult:
    """Hand an asset to the user (e.g. needs a human illustrator)."""
    return _call(lambda: _result(_pipeline().flag(asset_id, reason, by)))


@server.tool(annotations=RW)
def unflag(asset_id: str, by: UserOnly, action: Literal["retry", "waive"] = "retry",
           extra_attempts: Annotated[int, Field(ge=1, le=10)] = 1, notes: str | None = None) -> CallToolResult:
    """The user reopens a flagged asset with more attempts, or waives it."""
    return _call(lambda: _result(_pipeline().unflag(asset_id, by, action, extra_attempts, notes)))


@server.tool(annotations=RO)
def history(asset_id: str | None = None, limit: Annotated[int, Field(ge=1, le=1000)] = 100) -> CallToolResult:
    """Event log (claims, attempts, decisions, locks, gates), optionally for one asset."""
    return _call(lambda: _result(_pipeline().history(asset_id, limit)))


@server.tool(annotations=RW)
def handback() -> CallToolResult:
    """End-of-run summary for the user: counts, flags, unfinished work, assets needing a human finish,
    likely taste-revision candidates, the manifest, and a final contact sheet."""
    def go():
        out = _pipeline().handback()
        pages = [Path(x) for x in out.get("final_sheet", [])][:1]
        return _result(out, pages, ["The first page of the final sheet is shown as an overview (it may be "
                                    "downscaled); give the user the 'final_sheet' paths."] if pages else None)
    return _call(go)


@server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True,
                                        open_world_hint=False))
def place(target: Annotated[Literal["staging", "xcassets", "godot", "phaser"], Field(
              description="staging: files stay under the pipeline root, plus ART-INSTALL.md with copy steps "
              "(use for read-only repos). xcassets: imagesets/AppIcon in the Xcode asset catalog. godot: "
              "files at res://<destination> plus .import presets. phaser: files plus a Loader pack JSON. Atlases "
              "built by derive also get their frame data (atlas JSON, AtlasTexture/SpriteFrames, .spriteatlas).")],
          asset_ids: Annotated[list[str] | None, Field(description="Default: every approved asset")] = None,
          project_dir: Annotated[str | None, Field(
              description="The game project folder (default: the pipeline root). Only write into a "
              "project the user asked you to place into.")] = None,
          confirm_overwrite: Annotated[bool, Field(
              description="Replace files the pipeline didn't write instead of moving them to superseded/. "
              "Only when the user said so.")] = False,
          catalog: Annotated[str | None, Field(description="xcassets: catalog path under project_dir, when "
                                               "there is more than one")] = None,
          web_root: Annotated[str | None, Field(description="phaser: folder served at '/' (default public/ "
                                                "if present, else the project)")] = None,
          pack: Annotated[str | None, Field(description="phaser: pack file path under project_dir (default "
                                            "<web_root>/artpipeline-pack.json)")] = None,
          ) -> CallToolResult:
    """Write approved assets into an engine project layout and record every file in the manifest.
    Anything already there that the pipeline didn't write is moved to <root>/superseded/, never lost.
    Refused for engine targets while the style lock is provisional."""
    return _call(lambda: _result(_pipeline().place(target, asset_ids, project_dir, confirm_overwrite,
                                                   catalog, web_root, pack)))


@server.tool(annotations=RO)
def check_image(files: list[str],
                asset_id: Annotated[str | None, Field(
                    description="Check against this brief asset's own class, palette and processing, "
                    "without registering an attempt (a free pre-check). One file per call.")] = None,
                preset: Annotated[str | None, Field(description="Preset class to judge against, e.g. game_center_badge")] = None,
                size: Annotated[str | None, Field(description="Expected WxH")] = None,
                alpha: Literal["required", "forbidden", "any"] | None = None,
                palette: list[str] | None = None,
                backgrounds: list[str] | None = None) -> CallToolResult:
    """Objective checks on image files. With asset_id: a draft is run through that asset's real
    processing and checks without using an attempt. Without: stateless (no pipeline needed)."""
    from artpipeline.cli import run

    def go():
        if asset_id:
            p = _pipeline()
            res = [p.preflight(asset_id, f) for f in files]
            return _result({"pass": all(r["pass"] for r in res), "results": res})
        argv = ["check", *files]
        for flag_, val in (("--class", preset), ("--size", size), ("--alpha", alpha),
                           ("--palette", ",".join(palette) if palette else None),
                           ("--bg", ",".join(backgrounds) if backgrounds else None)):
            if val:
                argv += [flag_, val]
        code, out = run(argv)
        if isinstance(out, dict) and "error" in out:
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(out))],
                                  structured_content=out, is_error=True)
        return _result({"pass": code == 0, "results": out})
    return _call(go)


@server.tool(annotations=RO)
def contact_sheet(files: list[str], out_path: str,
                  sizes: list[int] | None = None, backgrounds: list[str] | None = None,
                  icon_mask: bool = False, pixel_art: bool = False) -> CallToolResult:
    """Stateless contact sheet of any image files at display sizes on backgrounds (no pipeline needed)."""
    from artpipeline.cli import run

    def go():
        argv = ["contact-sheet", out_path, *files, "--sizes", ",".join(map(str, sizes or [256, 64, 24]))]
        if backgrounds:
            argv += ["--bg", ",".join(backgrounds)]
        if icon_mask:
            argv.append("--icon-mask")
        if pixel_art:
            argv.append("--pixel")
        code, out = run(argv)
        if code:
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(out))],
                                  structured_content=out, is_error=True)
        return _result(out, [Path(p) for p in out["pages"]][:4])
    return _call(go)


def main() -> None:
    server.run("stdio")
