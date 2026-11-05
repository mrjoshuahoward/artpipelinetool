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

    sub.add_parser("export-manifest", help="Rewrite art-manifest.json")
    return p


def run(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    a = _parser().parse_args(argv)
    try:
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
                               references=a.references, notes=a.notes)
        elif a.cmd == "pass-gate":
            out = p.pass_gate(a.gate_id, a.by, a.notes)
        elif a.cmd == "flag":
            out = p.flag(a.asset_id, a.reason, a.by)
        elif a.cmd == "unflag":
            out = p.unflag(a.asset_id, a.by, a.action, a.extra_attempts, a.notes)
        elif a.cmd == "history":
            out = p.history(a.asset_id, a.limit)
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
