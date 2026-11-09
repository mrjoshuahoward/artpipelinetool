"""The `script` recipe (2.1 B4): an agent-written program that draws one asset.

The fallback for anything `svg`, `compose` and `derive` can't express (procedural patterns, custom
raster effects, an existing drawing script). The recipe names the script and every file it reads:

    build: {kind: script, script: art/scripts/badge.py, inputs: [art/scripts/lib/*.py, art/parts/*.svg],
            assets: [first-bloom], tokens: [gold, ink], params: {points: 5}, timeout: 60}

How it runs:

* The script and its declared `inputs` (paths or globs, relative to the pipeline root) are copied into
  a fresh temporary directory at the same relative paths, and the script runs there with that directory
  as its working directory. A file it reads but didn't declare simply isn't there, so the recorded
  inputs are the complete set and stale tracking can trust them.
* `.py` scripts run with artpipeline's own Python (so Pillow, resvg-py and `artpipeline` itself are
  importable); `.sh` with /bin/sh; anything else must be executable.
* The job is a JSON file whose path is argv[1] and $ARTPIPELINE_JOB: `asset`, `params`, `tokens`
  (only the declared ones, or all of them when `tokens` isn't given), `master`, `pixel_art`, `assets`
  (id → path of each declared dependency's approved file, copied in) and `output`, the file to write
  (`.svg` for vector classes, `.png` otherwise). `job()` below reads it.
* The environment is minimal and fixed (PATH, LANG, TZ=UTC, PYTHONHASHSEED=0, SOURCE_DATE_EPOCH=0,
  HOME = the temp dir); nothing else from the caller's environment leaks in.

Unlike the other kinds, the fingerprint hashes the **inputs** (script, declared files, dependencies,
tokens, params, asset fields, master), not the output, so `status()` can tell a script asset is stale
without running anything. The output's own hash is recorded too: a rebuild that produces the same
file as the approved attempt just refreshes that attempt's record instead of reopening it.

Scripts are code from the project, run on `build`/`dry_run` only, like a Makefile. They should not
use the network; artpipeline doesn't sandbox them beyond the working directory and environment."""
from __future__ import annotations

import glob
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from artpipeline.build.svg import BuildError, Compiled

BUILDER_VERSION = "script-1"
MAX_TIMEOUT = 600
_STDERR_LINES = 15

AssetResolver = Callable[[str], Path]


def job() -> dict[str, Any]:
    """Inside a script: the build job (see the module docstring)."""
    p = os.environ.get("ARTPIPELINE_JOB") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not p:
        raise SystemExit("not run by artpipeline build: no ARTPIPELINE_JOB")
    return json.loads(Path(p).read_text())


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _expand(root: Path, patterns: list[str], script: str) -> list[str]:
    """Declared inputs → sorted relative file paths. A pattern that matches nothing is an error."""
    out: set[str] = set()
    for pat in patterns:
        pp = PurePosixPath(pat)
        if pp.is_absolute() or ".." in pp.parts:
            raise BuildError(f"input '{pat}' must be relative to the pipeline root, without '..'")
        hits = [Path(h) for h in glob.glob(str(root / pat), recursive=True)]
        files = [h for h in hits if h.is_file()]
        for d in (h for h in hits if h.is_dir()):
            files += [f for f in d.rglob("*") if f.is_file()]
        if not files:
            raise BuildError(f"input '{pat}' matches no files")
        for f in files:
            try:
                rel = f.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                raise BuildError(f"input '{pat}' reaches outside the pipeline root ({f})") from None
            if "__pycache__" not in rel.split("/"):
                out.add(rel)
    out.discard(script)
    return sorted(out)


def _command(script: Path) -> list[str]:
    ext = script.suffix.lower()
    if ext == ".py":
        return [sys.executable, "-B", str(script)]
    if ext == ".sh":
        return ["/bin/sh", str(script)]
    if not os.access(script, os.X_OK):
        raise BuildError(f"script '{script.name}' is not a .py or .sh file and is not executable")
    return [str(script)]


def _validate_output(data: bytes, ext: str, script: str) -> None:
    if ext == ".svg":
        try:
            el = ET.fromstring(data)
        except ET.ParseError as e:
            raise BuildError(f"script '{script}' wrote an SVG that doesn't parse: {e}") from None
        if not el.tag.endswith("svg"):
            raise BuildError(f"script '{script}' wrote XML whose root is <{el.tag}>, not <svg>")
        return
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
    except Exception as e:  # noqa: BLE001 - any decoder error
        raise BuildError(f"script '{script}' wrote a file that isn't a readable image: {e}") from None


def compile_script(
    root: Path,
    *,
    script: str | None,
    inputs: list[str],
    deps: list[str],
    token_names: list[str] | None,
    params: dict[str, Any],
    tokens: dict[str, str],
    asset: dict[str, Any],
    master: tuple[int, int],
    vector: bool,
    pixel_art: bool = False,
    timeout: int = 60,
    assets: AssetResolver | None = None,
    run: bool = True,
) -> Compiled:
    if not script:
        raise BuildError("a script recipe needs script: <path>")
    src = root / script
    if not src.is_file():
        raise BuildError(f"script '{script}' not found")
    if deps and assets is None:
        raise BuildError("script dependencies need the pipeline (no resolver)")
    if asset.get("id") in deps:
        raise BuildError("an asset can't depend on itself")
    if token_names is None:
        given = dict(sorted(tokens.items()))
    else:
        missing = [t for t in token_names if t not in tokens]
        if missing:
            raise BuildError(f"unknown token(s) {missing}; the style has {sorted(tokens)}")
        given = {t: tokens[t] for t in sorted(token_names)}
    files = [script] + _expand(root, inputs, script)
    hashes = {f: _sha(root / f) for f in files}
    dep_files: dict[str, Path] = {}
    for aid in deps:
        p = assets(aid)  # BuildError when it isn't approved
        dep_files[aid] = p
        hashes[f"asset:{aid}"] = _sha(p)
    # Where the file is placed doesn't change what gets drawn, so the destination stays out of the job and the fingerprint.
    identity = {k: v for k, v in asset.items() if k != "destination"}
    ext = ".svg" if vector else ".png"
    str_params = {k: (str(v).lower() if isinstance(v, bool) else str(v)) for k, v in sorted(params.items())}
    key = {"builder": BUILDER_VERSION, "inputs": hashes, "tokens": given, "params": str_params,
           "asset": identity, "master": list(master), "pixel_art": pixel_art, "ext": ext}
    fingerprint = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()
    compiled = Compiled(svg=b"", fingerprint=fingerprint, inputs=dict(sorted(hashes.items())), tokens=given,
                        params=str_params, kind="script", builder=BUILDER_VERSION, ext=ext, asset=identity)
    if not run:
        return compiled

    with tempfile.TemporaryDirectory(prefix="artpipeline-script-") as tmp:
        work = Path(tmp) / "work"
        for f in files:
            dst = work / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / f, dst)
            if f == script:
                dst.chmod(dst.stat().st_mode | 0o100)
        dep_dir = Path(tmp) / "assets"
        dep_dir.mkdir()
        dep_paths = {}
        for aid, p in dep_files.items():
            d = dep_dir / f"{aid}{p.suffix.lower()}"
            shutil.copy2(p, d)
            dep_paths[aid] = str(d)
        out = Path(tmp) / "out" / f"built{ext}"
        out.parent.mkdir()
        job_file = Path(tmp) / "job.json"
        job_file.write_text(json.dumps({
            "asset": identity, "params": params, "tokens": given, "master": list(master),
            "pixel_art": pixel_art, "assets": dep_paths, "output": str(out), "format": ext[1:],
        }, indent=2, sort_keys=True))
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
               "TZ": "UTC", "PYTHONHASHSEED": "0", "SOURCE_DATE_EPOCH": "0", "PYTHONDONTWRITEBYTECODE": "1",
               "HOME": tmp, "TMPDIR": tmp, "ARTPIPELINE_JOB": str(job_file)}
        try:
            proc = subprocess.run(_command(work / script) + [str(job_file)], cwd=work, env=env,
                                  stdin=subprocess.DEVNULL, capture_output=True,
                                  timeout=min(timeout, MAX_TIMEOUT))
        except subprocess.TimeoutExpired:
            raise BuildError(f"script '{script}' ran past its {timeout}s timeout") from None
        except OSError as e:
            raise BuildError(f"script '{script}' could not start: {e}") from None
        if proc.returncode != 0:
            tail = "\n".join(proc.stderr.decode(errors="replace").strip().splitlines()[-_STDERR_LINES:])
            hint = ("\nOnly declared files are copied in: list every file the script reads in inputs."
                    if "No such file" in tail or "FileNotFoundError" in tail else "")
            raise BuildError(f"script '{script}' exited with {proc.returncode}" + (f":\n{tail}" if tail else "")
                             + hint)
        if not out.is_file():
            hint = "; a file it read may be missing from inputs" if proc.stderr else ""
            raise BuildError(f"script '{script}' finished without writing the output file "
                             f"(job['output'], a {ext} file){hint}")
        data = out.read_bytes()
    _validate_output(data, ext, script)
    compiled.svg = data
    compiled.output = hashlib.sha256(data).hexdigest()
    return compiled
