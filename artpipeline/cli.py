"""JSON CLI mirroring the MCP tools. stdout: one JSON document. Errors: JSON on stderr, exit 1."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from artpipeline import __version__
from artpipeline.errors import PipelineError
from artpipeline.pipeline import Pipeline
from artpipeline.store import Store


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="artpipeline", description=__doc__)
    p.add_argument("--version", action="version", version=f"artpipeline {__version__}")
    p.add_argument("--root", type=Path, help="Folder holding .artpipeline/ (default: search upward from cwd)")
    p.add_argument("--pretty", action="store_true", help="Indent JSON output")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="Create or refresh the pipeline from a brief")
    s.add_argument("brief", type=Path)

    s = sub.add_parser("status", help="Pipeline overview, or one asset in full")
    s.add_argument("asset_id", nargs="?")

    s = sub.add_parser("claim", help="Lease assets and get their work packets")
    s.add_argument("--agent", required=True)
    s.add_argument("-n", type=int, default=1)
    s.add_argument("--group")
    s.add_argument("--asset", action="append", dest="asset_ids")

    s = sub.add_parser("release", help="Give a claimed asset back to the queue")
    s.add_argument("asset_id")
    s.add_argument("--agent", required=True)

    s = sub.add_parser("register", help="Register an attempt (file + provenance) and run checks")
    s.add_argument("asset_id")
    s.add_argument("file", type=Path)
    s.add_argument("--agent", required=True)
    s.add_argument("--route", required=True, choices=["code_native", "agent_app", "image_gen", "human"])
    s.add_argument("--tool", required=True)
    s.add_argument("--model")
    s.add_argument("--prompt")
    s.add_argument("--seed")
    s.add_argument("--ref", action="append", dest="references", default=[])
    s.add_argument("--rights")
    s.add_argument("--notes")
    s.add_argument("--change", dest="change_from_previous", help="Required for attempt 2+")

    s = sub.add_parser("decide", help="Approve or reject the current attempt")
    s.add_argument("asset_id")
    s.add_argument("decision", choices=["approve", "reject"])
    s.add_argument("--by", required=True, choices=["user", "agent"])
    s.add_argument("--reason")

    s = sub.add_parser("lock-style", help="Lock the style after the user approves the heroes")
    s.add_argument("--by", required=True)
    s.add_argument("--block", help="Style block text (default: the brief's)")
    s.add_argument("--palette", help="Comma-separated hexes (default: the brief's)")
    s.add_argument("--hero", action="append", dest="hero_ids")
    s.add_argument("--ref", action="append", dest="references")
    s.add_argument("--notes")
    s.add_argument("--provisional", action="store_true",
                   help="With --by agent: provisional lock while the user is away")

    s = sub.add_parser("pass-gate", help="Record the user's sign-off on a review gate")
    s.add_argument("gate_id", type=int)
    s.add_argument("--by", required=True)
    s.add_argument("--notes")

    s = sub.add_parser("flag", help="Hand an asset to the user")
    s.add_argument("asset_id")
    s.add_argument("--reason", required=True)
    s.add_argument("--by", required=True, choices=["user", "agent"])

    s = sub.add_parser("unflag", help="User reopens (retry) or drops (waive) a flagged asset")
    s.add_argument("asset_id")
    s.add_argument("--by", required=True)
    s.add_argument("--action", choices=["retry", "waive"], default="retry")
    s.add_argument("--extra-attempts", type=int, default=1)
    s.add_argument("--notes")

    s = sub.add_parser("history", help="Event log, optionally for one asset")
    s.add_argument("asset_id", nargs="?")
    s.add_argument("--limit", type=int, default=200)

    s = sub.add_parser("review-sheet", help="Render a contact sheet of latest attempts and mark them reviewed")
    s.add_argument("asset_ids", nargs="*")
    s.add_argument("--pending", action="store_true", help="All assets awaiting review")
    s.add_argument("--gate", type=int, dest="gate_id")

    sub.add_parser("export-manifest", help="Rewrite art-manifest.json")
    sub.add_parser("handback", help="End-of-run summary with a final contact sheet")
    sub.add_parser("mcp", help="Run the MCP server on stdio")

    # Stateless utilities (no pipeline needed); they replace the skill's scripts.
    s = sub.add_parser("check", help="Objective checks on image files (exit 1 if any fail)")
    s.add_argument("files", nargs="+", type=Path)
    _class_flags(s)

    s = sub.add_parser("process", help="Process one source into a class master + renditions, then check it")
    s.add_argument("source", type=Path)
    s.add_argument("out_dir", type=Path)
    s.add_argument("--name", help="Output base name (default: source stem)")
    _class_flags(s)
    s.add_argument("--remove-bg", action="store_true")
    s.add_argument("--trim", action="store_true")
    s.add_argument("--clamp", choices=["hard", "soft", "off"])
    s.add_argument("--flatten", metavar="HEX")
    s.add_argument("--scales", help="Renditions as scale factors, e.g. 1,2,3 (suffix @Nx)")

    s = sub.add_parser("contact-sheet", help="Contact sheet of image files at display sizes on backgrounds")
    s.add_argument("out", type=Path)
    s.add_argument("files", nargs="+", type=Path)
    s.add_argument("--sizes", default="256,64,24")
    s.add_argument("--bg", default="#1C1C1E,#F2F2F7")
    s.add_argument("--labels")
    s.add_argument("--icon-mask", action="store_true")
    s.add_argument("--pixel", action="store_true")
    return p


def _class_flags(s: argparse.ArgumentParser) -> None:
    s.add_argument("--class", dest="klass", help="Preset class to start from (e.g. game_center_badge)")
    s.add_argument("--size", help="Master size WxH")
    s.add_argument("--alpha", choices=["required", "forbidden", "any"])
    s.add_argument("--palette", help="Comma-separated hexes, or a file with one hex per line")
    s.add_argument("--bg", dest="backgrounds", help="Comma-separated background hexes")
    s.add_argument("--min-in-palette", type=float)
    s.add_argument("--max-de", type=float)
    s.add_argument("--pixel-art", action="store_true")


def _hexes(v: str | None) -> list[str]:
    if not v:
        return []
    path = Path(v)
    if path.is_file():
        vals = [ln.split("//")[0].strip() for ln in path.read_text().splitlines()]
        return [x.split()[0] for x in vals if x]
    return [h.strip() for h in v.split(",") if h.strip()]


def _adhoc_class(a: argparse.Namespace, default_format: str):
    from artpipeline.presets import PRESETS
    from artpipeline.schema import AssetClass

    base = PRESETS[a.klass].model_dump() if a.klass else {"format": default_format, "master": (1024, 1024)}
    if a.klass and a.klass not in PRESETS:
        raise PipelineError("INVALID_ARGUMENT", f"Unknown preset '{a.klass}'.", known=sorted(PRESETS))
    if a.size:
        w, _, h = a.size.lower().partition("x")
        base["master"] = (int(w), int(h or w))
    if a.alpha:
        base["alpha"] = a.alpha
    if a.min_in_palette is not None:
        base["checks"]["palette_min_share"] = a.min_in_palette
    if a.max_de is not None:
        base["checks"]["palette_max_de"] = a.max_de
    if a.pixel_art:
        base["pixel_art"] = True
    proc = base.setdefault("processing", {})
    for flag, key in (("remove_bg", "remove_bg"), ("trim", "trim")):
        if getattr(a, flag, False):
            proc[key] = True
    if getattr(a, "clamp", None):
        proc["palette_clamp"] = a.clamp
    if getattr(a, "flatten", None):
        proc["flatten"] = a.flatten
    if getattr(a, "scales", None):
        base["renditions"] = [{"suffix": f"@{s.strip()}x", "scale": float(s)} for s in a.scales.split(",")]
    return AssetClass.model_validate(base)


def _stateless(a: argparse.Namespace) -> tuple[int, Any]:
    from artpipeline.checks import CheckContext, imaging_checker, options_for
    from artpipeline.imaging.analyze import analyze
    from artpipeline.imaging.render import RenderError, load_rgba
    from artpipeline.imaging.sheet import SheetItem, build_sheets

    if a.cmd == "contact-sheet":
        sizes = [int(x) for x in a.sizes.split(",")]
        labels = a.labels.split(",") if a.labels else [f.stem for f in a.files]
        items = [SheetItem(label=lab, image=load_rgba(f, (max(1024, max(sizes)),) * 2), sizes=sizes,
                           backgrounds=_hexes(a.bg), pixel_art=a.pixel, icon_mask=a.icon_mask)
                 for f, lab in zip(a.files, labels)]
        pages = build_sheets(items, a.out.parent, a.out.stem)
        return 0, {"pages": [str(p) for p in pages]}

    palette, bgs = _hexes(a.palette), _hexes(a.backgrounds)
    if a.cmd == "check":
        results = []
        for f in a.files:
            cls = _adhoc_class(a, "svg" if f.suffix.lower() == ".svg" else "png")
            try:
                img = load_rgba(f, tuple(cls.master))
            except RenderError as e:
                results.append({"file": str(f), "pass": False, "fail": [str(e)], "warn": []})
                continue
            size = tuple(cls.master) if (a.klass or a.size) else None
            fd = analyze(img, options_for(cls, palette, bgs or cls.review_backgrounds, size=size))
            results.append({"file": str(f), "pass": fd.passed, "fail": fd.fail, "warn": fd.warn,
                            "metrics": fd.metrics})
        return (0 if all(r["pass"] for r in results) else 1), results

    # process
    if not (a.klass or a.size):
        raise PipelineError("INVALID_ARGUMENT", "process needs --class or --size to know the master.")
    cls = _adhoc_class(a, "png")  # sources (incl. SVG) are processed into a raster master
    if not a.source.is_file():
        raise PipelineError("SOURCE_NOT_FOUND", f"Source file not found: {a.source}")
    res = imaging_checker(a.source, cls, CheckContext(palette=palette, backgrounds=bgs or cls.review_backgrounds,
                                                      out_dir=a.out_dir, name=a.name or a.source.stem))
    out = {"processed": str(res.processed_path) if res.processed_path else None,
           "renditions": {k: str(v) for k, v in res.renditions.items()}, **res.to_dict()}
    return (0 if res.passed else 1), out


def run(argv: list[str] | None = None) -> tuple[int, Any]:
    a = _parser().parse_args(argv)
    try:
        if a.cmd == "mcp":
            from artpipeline.mcp_server import main as mcp_main

            mcp_main()
            raise SystemExit(0)  # stdout belongs to the MCP transport; print nothing
        if a.cmd in ("check", "process", "contact-sheet"):
            return _stateless(a)
        if a.cmd == "init":
            _, out = Pipeline.init(a.brief, a.root)
            return 0, out
        store = Store.open(a.root) if a.root else Store.discover()
        p = Pipeline(store)
        if a.cmd == "status":
            out = p.status(a.asset_id)
        elif a.cmd == "claim":
            out = p.claim(a.agent, a.n, group=a.group, asset_ids=a.asset_ids)
        elif a.cmd == "release":
            out = p.release(a.asset_id, a.agent)
        elif a.cmd == "register":
            prov = {k: getattr(a, k) for k in
                    ("route", "tool", "model", "prompt", "seed", "references", "rights", "notes")}
            out = p.register_attempt(a.asset_id, a.file, a.agent, prov, a.change_from_previous)
        elif a.cmd == "decide":
            out = p.decide(a.asset_id, a.decision, a.by, a.reason)
        elif a.cmd == "lock-style":
            pal = [h.strip() for h in a.palette.split(",")] if a.palette else None
            out = p.lock_style(a.by, a.block, palette=pal, hero_ids=a.hero_ids,
                               references=a.references, notes=a.notes, provisional=a.provisional)
        elif a.cmd == "pass-gate":
            out = p.pass_gate(a.gate_id, a.by, a.notes)
        elif a.cmd == "flag":
            out = p.flag(a.asset_id, a.reason, a.by)
        elif a.cmd == "unflag":
            out = p.unflag(a.asset_id, a.by, a.action, a.extra_attempts, a.notes)
        elif a.cmd == "history":
            out = p.history(a.asset_id, a.limit)
        elif a.cmd == "review-sheet":
            out = p.review_sheet(a.asset_ids, pending_review=a.pending, gate_id=a.gate_id)
        elif a.cmd == "handback":
            out = p.handback()
        elif a.cmd == "export-manifest":
            out = p.export_manifest()
        else:  # pragma: no cover
            raise AssertionError(a.cmd)
        return 0, out
    except PipelineError as e:
        return 1, e.to_dict()


def main(argv: list[str] | None = None) -> None:
    pretty = "--pretty" in (argv if argv is not None else sys.argv[1:])
    code, out = run(argv)
    text = json.dumps(out, indent=2 if pretty else None)
    print(text, file=sys.stderr if code else sys.stdout)
    sys.exit(code)


if __name__ == "__main__":
    main()
