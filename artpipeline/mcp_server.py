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
from pydantic import Field

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
4. handback() at the end. by="user" means the user said so in this conversation; never set it on
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


@server.tool(annotations=RW)
def review_sheet(asset_ids: list[str] | None = None,
                 pending_review: bool = False,
                 gate_id: int | None = None) -> CallToolResult:
    """Contact sheet of the latest attempts: shown inline as one strip per asset; full pages are saved
    for the user (paths in 'pages'). Marks those attempts as reviewed."""
    def go():
        sheet = _pipeline().review_sheet(asset_ids, pending_review=pending_review, gate_id=gate_id)
        imgs, notes_ = _strip_images(sheet)
        return _result(sheet, imgs, notes_)
    return _call(go)


@server.tool(annotations=RW)
def decide(asset_id: str, decision: Literal["approve", "reject"], by: By,
           reason: Annotated[str | None, Field(description="Required to reject: what specifically failed")] = None,
           ) -> CallToolResult:
    """Approve or reject the asset's current attempt (it must have been on a sheet or preview)."""
    return _call(lambda: _result(_pipeline().decide(asset_id, decision, by, reason)))


@server.tool(annotations=RW)
def lock_style(by: Annotated[Literal["user", "agent"], Field(
                   description="'user' only after the user approved the heroes in this conversation. "
                   "'agent' is allowed only with provisional=true.")],
               style_block: Annotated[str | None, Field(description="Default: the brief's style block")] = None,
               palette: list[str] | None = None,
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
        provisional=provisional)))


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


@server.tool(annotations=RO)
def check_image(files: list[str],
                preset: Annotated[str | None, Field(description="Preset class to judge against, e.g. game_center_badge")] = None,
                size: Annotated[str | None, Field(description="Expected WxH")] = None,
                alpha: Literal["required", "forbidden", "any"] | None = None,
                palette: list[str] | None = None,
                backgrounds: list[str] | None = None) -> CallToolResult:
    """Stateless objective checks on any image files (no pipeline needed)."""
    from artpipeline.cli import run

    def go():
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
