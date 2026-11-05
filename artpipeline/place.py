"""Placement targets: where approved files go in a project. This module only plans; the pipeline
does the writing (moving anything it didn't write to superseded/) and records every file.

Targets (spec §7):
  staging   <root>/<destination> (done on approval) plus ART-INSTALL.md with copy steps
  xcassets  <name>.imageset / AppIcon.appiconset with Contents.json in the project's asset catalog
  godot     <project>/<destination> plus a .import preset per file (never replaces an existing one)
  phaser    <project>/<destination> plus a Loader pack file listing every placed image
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from artpipeline.schema import AssetClass

TARGETS = ("staging", "xcassets", "godot", "phaser")
INSTALL_NAME = "ART-INSTALL.md"
PACK_SECTION = "artpipeline"

# Built-in classes that never go into an app bundle's asset catalog.
NOT_IN_CATALOG = {
    "game_center_badge": "Game Center art is uploaded in App Store Connect (or a .gamekit bundle in Xcode), "
                         "not the asset catalog.",
    "store_screenshot": "App Store screenshots are uploaded in App Store Connect.",
    "ios_app_icon_layer": "Icon Composer layers go into an .icon file built in Icon Composer.",
}
_SKIP_DIRS = {"DerivedData", "Pods", "build", "node_modules", ".git", ".artpipeline", "superseded", ".godot"}
_SCALE = re.compile(r"@([123])x$")
_XC_INFO = {"author": "xcode", "version": 1}


class PlacementError(ValueError):
    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


@dataclass
class Item:
    """One approved asset, ready to place."""

    asset_id: str
    class_name: str
    klass: AssetClass
    destination: str             # from the brief, relative
    master: Path                 # absolute
    renditions: dict[str, Path]  # suffix -> absolute path


@dataclass
class Write:
    dest: Path
    src: Path | None = None
    data: bytes | None = None
    asset_id: str = "*"
    keep_if_exists: bool = False  # e.g. a Godot .import: never replace the user's own settings


@dataclass
class Plan:
    writes: list[Write] = field(default_factory=list)
    owned_dirs: list[Path] = field(default_factory=list)  # wholly ours (imagesets): strays are superseded
    skipped: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    info: dict[str, Any] = field(default_factory=dict)

    def add(self, dest: Path, item: Item | None = None, **kw: Any) -> None:
        self.writes.append(Write(dest=dest, asset_id=item.asset_id if item else "*", **kw))


def main_dest(item: Item, base: Path) -> Path:
    d = base / item.destination
    return d.with_suffix(item.master.suffix) if d.suffix.lower() != item.master.suffix.lower() else d


def file_pairs(item: Item, base: Path) -> list[tuple[Path, Path]]:
    """Master at the destination, renditions beside it under their own names."""
    d = main_dest(item, base)
    return [(item.master, d)] + [(p, d.parent / p.name) for p in item.renditions.values()]


def build(target: str, items: list[Item], root: Path, project: Path, *, catalog: str | None = None,
          web_root: str | None = None, pack: str | None = None, stamp: str = "") -> Plan:
    if target == "staging":
        return _staging(items, root, project, stamp)
    if target == "xcassets":
        return _xcassets(items, project, catalog)
    if target == "godot":
        return _godot(items, project)
    if target == "phaser":
        return _phaser(items, project, web_root, pack)
    raise PlacementError(f"Unknown target '{target}'.", hint=f"Use one of {list(TARGETS)}.")


# ---------------------------------------------------------------- staging

def _staging(items: list[Item], root: Path, project: Path, stamp: str) -> Plan:
    plan = Plan()
    rels: list[tuple[str, str]] = []
    for it in items:
        for src, dest in file_pairs(it, root):
            plan.add(dest, it, src=src)
            rels.append((it.asset_id, dest.relative_to(root).as_posix()))
    target = str(project) if project != root else "<your project>"
    lines = [
        "# Installing the approved art",
        "",
        f"Written by artpipeline ({stamp}). {len(items)} assets, {len(rels)} files, each at its brief "
        "destination relative to this folder.",
        "",
        "| Asset | File |",
        "|---|---|",
        *[f"| {a} | `{f}` |" for a, f in rels],
        "",
        "## Copy into the project",
        "",
        "Run from this folder. `rsync -R` keeps each file's relative path.",
        "",
        "```bash",
        "rsync -R \\",
        *[f"  '{f}' \\" for _, f in rels],
        f"  '{target}/'",
        "```",
        "",
        "Or place them with `artpipeline place --target xcassets|godot|phaser --project <dir>`.",
        "",
    ]
    plan.add(root / INSTALL_NAME, data="\n".join(lines).encode())
    plan.info["install"] = INSTALL_NAME
    return plan


# ---------------------------------------------------------------- xcassets

def find_catalogs(project: Path) -> list[Path]:
    out = []
    for dirpath, dirnames, _ in os.walk(project):
        keep = []
        for d in dirnames:
            if d.endswith(".xcassets"):
                out.append(Path(dirpath) / d)
            elif d not in _SKIP_DIRS and not d.startswith("."):
                keep.append(d)
        dirnames[:] = keep
    return sorted(out)


def _catalog(project: Path, catalog: str | None) -> Path:
    if catalog:
        p = (project / catalog).resolve()
        if p.suffix != ".xcassets" or not p.is_dir():
            raise PlacementError(f"{p} is not an .xcassets folder.")
        return p
    found = find_catalogs(project)
    if len(found) == 1:
        return found[0]
    if not found:
        raise PlacementError(f"No .xcassets catalog under {project}.",
                             hint="Pass catalog='<path to Assets.xcassets>' or the right project folder.")
    raise PlacementError(f"Several asset catalogs under {project}: "
                         f"{[str(f.relative_to(project)) for f in found]}",
                         hint="Pass catalog='<one of them>'.")


def _set_name(item: Item) -> str:
    return _SCALE.sub("", PurePosixPath(item.destination).stem)


def _xcassets(items: list[Item], project: Path, catalog: str | None) -> Plan:
    plan = Plan()
    cat = _catalog(project, catalog)
    plan.info["catalog"] = cat.relative_to(project).as_posix() if cat.is_relative_to(project) else str(cat)
    icons = [it for it in items if it.klass.icon_mask and it.klass.alpha == "forbidden"
             and it.class_name not in NOT_IN_CATALOG]
    names: dict[str, str] = {}
    for it in items:
        if it.class_name in NOT_IN_CATALOG:
            plan.skipped.append({"asset_id": it.asset_id, "reason": NOT_IN_CATALOG[it.class_name]})
            continue
        if it in icons:
            name = "AppIcon" if len(icons) == 1 else _set_name(it)
            folder = cat / f"{name}.appiconset"
            w, h = it.klass.master
            if (w, h) != (1024, 1024):
                plan.skipped.append({"asset_id": it.asset_id,
                                     "reason": f"app icons need a 1024x1024 master, this is {w}x{h}"})
                continue
            fn = f"{name}-1024{it.master.suffix}"
            images = [{"filename": fn, "idiom": "universal", "platform": "ios", "size": "1024x1024"}]
            plan.add(folder / fn, it, src=it.master)
        else:
            scaled: dict[str, Path] = {}
            name = _set_name(it)
            folder = cat / f"{name}.imageset"
            for suffix, p in it.renditions.items():
                m = _SCALE.search(suffix)
                if m:
                    scaled[m.group(1)] = p
            images = []
            if scaled:
                for k in sorted(scaled):
                    images.append({"filename": scaled[k].name, "idiom": "universal", "scale": f"{k}x"})
                    plan.add(folder / scaled[k].name, it, src=scaled[k])
            else:  # Xcode's "Single Scale"
                images.append({"filename": it.master.name, "idiom": "universal"})
                plan.add(folder / it.master.name, it, src=it.master)
        if name in names:
            raise PlacementError(f"'{names[name]}' and '{it.asset_id}' both map to the catalog entry '{name}'.",
                                 hint="Give them different destination file names in the brief.")
        names[name] = it.asset_id
        doc: dict[str, Any] = {"images": images, "info": _XC_INFO}
        if images[0]["filename"].lower().endswith(".svg"):
            doc["properties"] = {"preserves-vector-representation": True}
        plan.add(folder / "Contents.json", it, data=(json.dumps(doc, indent=2) + "\n").encode())
        plan.owned_dirs.append(folder)
    if any(it.klass.pixel_art for it in items):
        plan.notes.append("Pixel art: set filteringMode = .nearest on the SpriteKit textures (or "
                          "magnificationFilter = .nearest on layers); the catalog can't carry it.")
    return plan


# ---------------------------------------------------------------- godot

def _godot_import(k: AssetClass) -> bytes:
    params = {
        "compress/mode": 0,                      # lossless: UI and 2D art
        "mipmaps/generate": "false",
        "process/fix_alpha_border": "false" if k.alpha == "forbidden" else "true",
        "detect_3d/compress_to": 0,              # don't silently switch to VRAM compression
    }
    body = "\n".join(f"{k_}={v}" for k_, v in params.items())
    return f'[remap]\n\nimporter="texture"\ntype="CompressedTexture2D"\n\n[params]\n\n{body}\n'.encode()


def _godot(items: list[Item], project: Path) -> Plan:
    if not (project / "project.godot").is_file():
        raise PlacementError(f"{project} has no project.godot.", hint="Pass the Godot project folder.")
    plan = Plan()
    for it in items:
        for src, dest in file_pairs(it, project):
            plan.add(dest, it, src=src)
            plan.add(dest.with_name(dest.name + ".import"), it, data=_godot_import(it.klass),
                     keep_if_exists=True)
    plan.info["res_paths"] = {it.asset_id: "res://" + main_dest(it, project).relative_to(project).as_posix()
                              for it in items}
    if any(it.klass.pixel_art for it in items):
        plan.notes.append("Pixel art: set Project Settings > Rendering > Textures > Default Texture Filter to "
                          "Nearest, or texture_filter = Nearest on the nodes. Godot 4 keeps filtering off "
                          "the import.")
    plan.notes.append("Existing .import files were left alone; Godot reimports the new files on focus.")
    return plan


# ---------------------------------------------------------------- phaser

def _phaser(items: list[Item], project: Path, web_root: str | None, pack: str | None) -> Plan:
    plan = Plan()
    wr = project / (web_root if web_root is not None else ("public" if (project / "public").is_dir() else "."))
    wr = wr.resolve()
    pack_path = (project / pack).resolve() if pack else wr / "artpipeline-pack.json"
    entries: dict[str, dict[str, str]] = {}
    for it in items:
        for i, (src, dest) in enumerate(file_pairs(it, project)):
            plan.add(dest, it, src=src)
            try:
                url = dest.resolve().relative_to(wr).as_posix()
            except ValueError:
                plan.notes.append(f"{dest.relative_to(project)} is outside the web root ({wr.name}/), so the "
                                  f"game can't load it by URL; it is not in the pack.")
                continue
            key = it.asset_id if i == 0 else it.asset_id + src.stem.removeprefix(main_dest(it, project).stem)
            entries[key] = {"type": "svg" if dest.suffix.lower() == ".svg" else "image", "key": key, "url": url}
    doc: dict[str, Any] = {}
    if pack_path.is_file():
        try:
            doc = json.loads(pack_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise PlacementError(f"Existing pack {pack_path} isn't valid JSON ({e}).",
                                 hint="Fix or move it, or pass pack='<another path>'.") from e
        if not isinstance(doc, dict):
            raise PlacementError(f"Existing pack {pack_path} isn't a Phaser pack object.")
    section = doc.get(PACK_SECTION) if isinstance(doc.get(PACK_SECTION), dict) else {}
    kept = [f for f in section.get("files", []) if isinstance(f, dict) and f.get("key") not in entries]
    section["files"] = sorted(kept + list(entries.values()), key=lambda f: str(f.get("key")))
    doc[PACK_SECTION] = section
    plan.add(pack_path, data=(json.dumps(doc, indent=2) + "\n").encode())
    try:
        pack_url = pack_path.relative_to(wr).as_posix()
    except ValueError:
        pack_url = str(pack_path)
    plan.info["pack"] = pack_path.relative_to(project).as_posix() if pack_path.is_relative_to(project) \
        else str(pack_path)
    plan.info["load"] = f'this.load.pack("{PACK_SECTION}", "{pack_url}");  // in a preload(); keys are asset ids'
    return plan
