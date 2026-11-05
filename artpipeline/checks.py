"""Objective checks run when an attempt is registered.

M1 ships basic checks (decodable, master size, alpha rule). M2 replaces `basic_checker`
with the full imaging pipeline ported from the skill's scripts (processing, renditions,
halo, palette share, contrast, greyscale read)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from artpipeline.schema import AssetClass


@dataclass
class CheckContext:
    palette: list[str]
    backgrounds: list[str]


@dataclass
class CheckResult:
    passed: bool
    fail: list[str] = field(default_factory=list)
    warn: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    processed_path: Path | None = None
    renditions: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"pass": self.passed, "fail": self.fail, "warn": self.warn, "metrics": self.metrics}


Checker = Callable[[Path, AssetClass, CheckContext], CheckResult]


def basic_checker(source: Path, cls: AssetClass, ctx: CheckContext) -> CheckResult:
    if source.suffix.lower() == ".svg":
        return CheckResult(
            passed=True,
            warn=["SVG source: rendering and pixel checks arrive in M2; only registered."],
        )
    from PIL import Image, UnidentifiedImageError

    fail: list[str] = []
    metrics: dict[str, Any] = {}
    try:
        with Image.open(source) as img:
            img.load()
            w, h = img.size
            metrics["size"] = f"{w}x{h}"
            rgba = img.convert("RGBA")
    except (UnidentifiedImageError, OSError) as e:
        return CheckResult(passed=False, fail=[f"not a decodable image: {e}"])

    if (w, h) != tuple(cls.master):
        fail.append(f"size {w}x{h} != master {cls.master[0]}x{cls.master[1]}")

    amin, _ = rgba.getchannel("A").getextrema()
    has_alpha = amin < 255
    corners = [rgba.getpixel(p)[3] for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    metrics["alpha"] = {"has_transparency": has_alpha, "corner_alpha": corners}
    if cls.alpha == "required" and (not has_alpha or max(corners) > 10):
        fail.append("transparent background required (corners are not transparent)")
    if cls.alpha == "forbidden" and has_alpha:
        fail.append("must be fully opaque (no alpha allowed for this class)")

    return CheckResult(passed=not fail, fail=fail, metrics=metrics)
