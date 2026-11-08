from __future__ import annotations

import json
import subprocess
import sys

from artpipeline.cli import run
from conftest import make_manifest, write_brief


def test_cli_flow(tmp_path, good_png, monkeypatch):
    brief = write_brief(tmp_path / "brief.md", make_manifest())
    code, out = run(["init", str(brief)])
    assert code == 0 and out["heroes"] == ["badge_00", "badge_01"]

    monkeypatch.chdir(tmp_path / ".artpipeline")  # discovery walks upward
    code, out = run(["claim", "--agent", "main", "-n", "2"])
    assert code == 0 and len(out["claimed"]) == 2

    code, out = run(["register", "badge_00", str(good_png), "--agent", "main",
                     "--route", "image_gen", "--tool", "gpt-image-2", "--seed", "42", "--ref", "a.png"])
    assert code == 0 and out["status"] == "awaiting_review"

    code, out = run(["decide", "badge_00", "approve", "--by", "agent"])
    assert code == 1 and out["error"] == "NOT_REVIEWED" and out["hint"]

    code, out = run(["status", "badge_00"])
    prov = out["attempts"][0]["provenance"]
    assert prov["seed"] == "42" and prov["references"] == ["a.png"]


def test_cli_errors_go_to_stderr(tmp_path):
    r = subprocess.run([sys.executable, "-m", "artpipeline.cli", "status"],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 1 and r.stdout == ""
    assert json.loads(r.stderr)["error"] == "NO_PIPELINE"
