"""Building assets from committed recipes (2.1). Kinds: `svg` (B1), `compose` (B2) and `derive`
(B3); `script` follows. A build is deterministic: the same recipe files, params, tokens and fonts give
the same bytes, so artpipeline can tell when an asset is stale and rebuild it."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from artpipeline.build.compose import AssetResolver, compile_compose
from artpipeline.build.derive import compile_derive
from artpipeline.build.svg import BuildError, Compiled, compile_svg, describe_change

__all__ = ["AssetResolver", "BuildError", "Compiled", "compile_recipe", "describe_change"]


def compile_recipe(root: Path, build: dict[str, Any], *, tokens: dict[str, str], asset: dict[str, Any],
                   master: tuple[int, int], assets: AssetResolver | None = None,
                   pixel_art: bool = False) -> Compiled:
    kind = build.get("kind", "svg")
    params = build.get("params") or {}
    if kind == "svg":
        return compile_svg(root, source=build.get("source"), template=build.get("template"),
                           params=params, tokens=tokens, asset=asset, master=master)
    if kind == "compose":
        return compile_compose(root, layers=build.get("layers") or [], background=build.get("background"),
                               params=params, tokens=tokens, asset=asset, master=master, assets=assets)
    if kind == "derive":
        cell = build.get("cell")
        return compile_derive(root, frames=build.get("frames") or [], layout=build.get("layout") or "pack",
                              cell=tuple(cell) if cell else None, columns=build.get("columns"),
                              padding=build.get("padding", 2), extrude=build.get("extrude", 0),
                              trim=build.get("trim"), animation=build.get("animation"), asset=asset,
                              master=master, pixel_art=pixel_art, assets=assets)
    raise BuildError(f"recipe kind '{kind}' is not supported yet")
