"""Building assets from committed recipes (2.1). B1 ships the `svg` recipe kind; `compose`,
`derive` and `script` follow. A build is deterministic: the same recipe files, params and tokens
give the same bytes, so artpipeline can tell when an asset is stale and rebuild it."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from artpipeline.build.svg import BuildError, Compiled, compile_svg, describe_change

__all__ = ["BuildError", "Compiled", "compile_recipe", "describe_change"]


def compile_recipe(root: Path, build: dict[str, Any], *, tokens: dict[str, str], asset: dict[str, Any],
                   master: tuple[int, int]) -> Compiled:
    kind = build.get("kind", "svg")
    if kind != "svg":
        raise BuildError(f"recipe kind '{kind}' is not supported yet")
    return compile_svg(root, source=build.get("source"), template=build.get("template"),
                       params=build.get("params") or {}, tokens=tokens, asset=asset, master=master)
