"""The attempt checker: process a registered source into the class's master and renditions,
then run the objective checks. A refusal by a processing step (e.g. it would upscale) is a
check failure, so it feeds the retry loop like any other."""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from artpipeline.imaging.analyze import CheckOptions, analyze
from artpipeline.imaging.process import (
    ProcessError, fit_to_master, flatten, palette_clamp, remove_background, resize_rendition, trim,
)
from artpipeline.imaging.render import RenderError, is_svg, load_rgba, render_svg
from artpipeline.schema import AssetClass

SOFT_CLAMP = 0.3


@dataclass
class CheckContext:
    palette: list[str]
    backgrounds: list[str]
    out_dir: Path
    name: str


@dataclass
class CheckResult:
    passed: bool
    fail: list[str] = field(default_factory=list)
    warn: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    processed_path: Path | None = None
    renditions: dict[str, Path] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"pass": self.passed, "fail": self.fail, "warn": self.warn, "metrics": self.metrics}


Checker = Callable[[Path, AssetClass, CheckContext], CheckResult]


def options_for(cls: AssetClass, palette: list[str], backgrounds: list[str],
                size: tuple[int, int] | None = None) -> CheckOptions:
    c = cls.checks
    return CheckOptions(
        size=size or tuple(cls.master), alpha=cls.alpha, halo=c.halo, palette=palette,
        palette_min_share=c.palette_min_share, palette_max_de=c.palette_max_de,
        backgrounds=backgrounds, min_contrast=c.min_contrast, greyscale_read=c.greyscale_read,
    )


def imaging_checker(source: Path, cls: AssetClass, ctx: CheckContext) -> CheckResult:
    warn: list[str] = []
    renditions: dict[str, Path] = {}
    svg_src = is_svg(source)
    p = cls.processing
    ctx.out_dir.mkdir(parents=True, exist_ok=True)

    def post(img: Image.Image) -> Image.Image:
        # Flatten first: clamping before compositing would let anti-aliased edges blend off-palette.
        if p.flatten:
            img = flatten(img, p.flatten)
        if p.palette_clamp != "off" and ctx.palette:
            img = palette_clamp(img, ctx.palette, 0.0 if p.palette_clamp == "hard" else SOFT_CLAMP)
        return img

    try:
        if cls.is_vector:
            img = render_svg(source, *cls.master)
            processed = ctx.out_dir / f"{ctx.name}.svg"
            shutil.copy2(source, processed)
            if p.palette_clamp != "off" or p.flatten or p.remove_bg or p.trim:
                warn.append("processing steps are ignored for vector classes; fix the SVG itself")
        else:
            img = render_svg(source, *cls.master) if svg_src else load_rgba(source)
            if p.remove_bg:
                if svg_src:
                    warn.append("remove_bg skipped: SVG sources have their own transparency")
                else:
                    img = remove_background(img)
            if p.trim:
                img = trim(img)
            img = fit_to_master(img, tuple(cls.master), pixel_art=cls.pixel_art, pad=p.trim)
            if p.palette_clamp != "off" and not ctx.palette:
                warn.append("palette_clamp requested but no palette is set (brief style or lock)")
            img = post(img)
            processed = ctx.out_dir / f"{ctx.name}.{cls.format}"
            _save(img, processed, cls.format, cls.alpha)

        rerender = cls.is_vector or (svg_src and not p.trim)
        for r in cls.renditions:
            size = tuple(r.size) if r.size else (round(cls.master[0] * r.scale), round(cls.master[1] * r.scale))
            if rerender:  # sharper than downscaling
                rimg = render_svg(source, *size)
                if not cls.is_vector:
                    rimg = post(rimg)
            else:
                rimg = resize_rendition(img, size, pixel_art=cls.pixel_art)
            fmt = "png" if cls.is_vector else cls.format
            rpath = ctx.out_dir / "renditions" / f"{ctx.name}{r.suffix}.{fmt}"
            rpath.parent.mkdir(exist_ok=True)
            _save(rimg, rpath, fmt, cls.alpha)
            renditions[r.suffix] = rpath
    except (RenderError, ProcessError) as e:
        return CheckResult(passed=False, fail=[str(e)], warn=warn)

    f = analyze(img, options_for(cls, ctx.palette, ctx.backgrounds))
    if renditions:
        f.metrics["renditions"] = {k: "x".join(map(str, Image.open(v).size)) for k, v in renditions.items()}
    return CheckResult(passed=f.passed, fail=f.fail, warn=warn + f.warn, metrics=f.metrics,
                       processed_path=processed, renditions=renditions)


def _save(img: Image.Image, path: Path, fmt: str, alpha: str = "any") -> None:
    # Stores (App Store icons, Game Center art, screenshots) reject files that merely *have* an alpha
    # channel, even a fully opaque one. A forbidden-alpha image that is opaque is written as plain RGB;
    # one that isn't keeps its alpha so the failed check matches what is on disk.
    if alpha == "forbidden" and img.mode == "RGBA" and img.getchannel("A").getextrema()[0] == 255:
        img = img.convert("RGB")
    if fmt == "jpg":
        img.convert("RGB").save(path, "JPEG", quality=95)
    elif fmt == "webp":
        img.save(path, "WEBP", lossless=True)
    else:
        img.save(path, "PNG")
