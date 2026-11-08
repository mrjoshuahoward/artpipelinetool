"""Brief manifest schema (v2). Asset classes are data; presets live in presets.py."""
from __future__ import annotations

import copy
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

HEX = r"^#[0-9A-Fa-f]{6}$"
ASSET_ID = r"^[a-z0-9][a-z0-9_.-]*$"
TOKEN_NAME = r"^[A-Za-z][A-Za-z0-9_-]*$"
RASTER_FORMATS = ("png", "webp", "jpg")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Rendition(_Strict):
    """An extra output derived from the master: by scale factor or explicit pixel size."""

    suffix: str
    scale: float | None = Field(default=None, gt=0)
    size: tuple[int, int] | None = None

    @model_validator(mode="after")
    def _one_of(self) -> "Rendition":
        if (self.scale is None) == (self.size is None):
            raise ValueError("rendition needs exactly one of 'scale' or 'size'")
        return self


class CheckConfig(_Strict):
    halo: bool = True
    palette_min_share: float | None = Field(default=0.85, ge=0, le=1)  # null disables
    palette_max_de: float = 12.0
    min_contrast: float | None = Field(default=1.6, gt=0)  # warn-only, as in the skill
    greyscale_read: bool = True


class Processing(_Strict):
    trim: bool = False
    remove_bg: bool = False
    palette_clamp: Literal["hard", "soft", "off"] = "off"
    flatten: str | None = Field(default=None, pattern=HEX)


class AssetClass(_Strict):
    format: Literal["png", "webp", "jpg", "svg"]
    master: tuple[int, int]
    alpha: Literal["required", "forbidden", "any"] = "any"
    renditions: list[Rendition] = Field(default_factory=list)
    display_sizes: list[int] = Field(default_factory=list)
    review_backgrounds: list[str] = Field(default_factory=list)
    checks: CheckConfig = Field(default_factory=CheckConfig)
    processing: Processing = Field(default_factory=Processing)
    pixel_art: bool = False
    icon_mask: bool = False            # round tiles like an iOS icon on contact sheets

    @field_validator("review_backgrounds")
    @classmethod
    def _hexes(cls, v: list[str]) -> list[str]:
        _check_hexes(v)
        return v

    @property
    def is_vector(self) -> bool:
        return self.format == "svg"


def _recipe_path(v: str | None) -> str | None:
    if v is None:
        return v
    p = PurePosixPath(v)
    if p.is_absolute() or not p.name:
        raise ValueError("recipe paths are relative to the pipeline root (commit them with the project)")
    return v


COLOR_REF = r"^(#[0-9A-Fa-f]{6}|\$[A-Za-z][A-Za-z0-9_-]*|\{\{[^{}]+\}\})$"


class Shadow(_Strict):
    dx: float = 0
    dy: float = 8
    blur: float = Field(default=12, ge=0)
    color: str = Field(default="#000000", pattern=COLOR_REF)
    opacity: float = Field(default=0.35, ge=0, le=1)


class Layer(_Strict):
    """One layer of a `compose` recipe, drawn bottom to top. Exactly one of svg, image, asset, text
    or fill says what it is. Boxes are in master pixels; `size` defaults to the whole canvas."""

    svg: str | None = None           # an SVG recipe file (tokens, params, shapes, ap:text all work)
    image: str | None = None         # a raster or SVG file, embedded
    asset: str | None = None         # another asset's approved output (key art from approved sprites)
    text: str | None = None          # drawn as outlines from `font`; newlines break lines
    fill: str | None = Field(default=None, pattern=COLOR_REF)   # a solid (rounded) rectangle

    at: tuple[float, float] = (0, 0)
    size: tuple[float, float] | None = None
    fit: Literal["contain", "cover", "stretch"] = "contain"
    radius: float = Field(default=0, ge=0)       # rounded corners for fill, image and asset layers
    opacity: float = Field(default=1, ge=0, le=1)
    rotate: float = 0                             # degrees clockwise about the box centre
    shadow: Shadow | None = None
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)  # svg layers

    font: str | None = None
    font_size: float | None = Field(default=None, gt=0)
    color: str = Field(default="#000000", pattern=COLOR_REF)
    anchor: Literal["start", "middle", "end"] = "start"
    valign: Literal["baseline", "top", "middle", "bottom"] = "baseline"
    max_width: float | None = Field(default=None, gt=0)
    shrink: bool = False                          # scale the text down to fit max_width instead of wrapping
    line_height: float = Field(default=1.2, gt=0)
    letter_spacing: float = 0
    axes: dict[str, float] = Field(default_factory=dict)   # variable font axes, e.g. {wght: 800}
    stroke: str | None = Field(default=None, pattern=COLOR_REF)
    stroke_width: float = Field(default=0, ge=0)

    @field_validator("svg", "image", "font")
    @classmethod
    def _paths(cls, v: str | None) -> str | None:
        return _recipe_path(v)

    @model_validator(mode="after")
    def _one_kind(self) -> "Layer":
        kinds = [k for k in ("svg", "image", "asset", "text", "fill") if getattr(self, k) is not None]
        if len(kinds) != 1:
            raise ValueError(f"a layer needs exactly one of svg, image, asset, text or fill (got {kinds or 'none'})")
        if self.text is not None and not (self.font and self.font_size):
            raise ValueError("a text layer needs font (a committed .ttf/.otf) and font_size")
        if self.params and self.svg is None:
            raise ValueError("layer params apply only to svg layers")
        return self

    @property
    def kind(self) -> str:
        return next(k for k in ("svg", "image", "asset", "text", "fill") if getattr(self, k) is not None)


class Animation(_Strict):
    fps: float = Field(default=12, gt=0)
    loop: bool = True
    sequence: list[str] = Field(default_factory=list)  # play order; may repeat frames (default: frames)


class BuildSpec(_Strict):
    """How artpipeline builds an asset itself (2.1). Paths are relative to the pipeline root.
    kind 'svg': an SVG source and/or a shared template with <ap:slot/>, filled with params and the
    style's named colour tokens. kind 'compose': a stack of layers (SVG recipes, images, other
    approved assets, text, fills) on a canvas the size of the master. kind 'derive': other approved
    assets packed into one sprite sheet or texture atlas the size of the master."""

    kind: Literal["svg", "compose", "derive"] = "svg"
    source: str | None = None
    template: str | None = None
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)
    background: str | None = Field(default=None, pattern=COLOR_REF)   # compose
    layers: list[Layer] = Field(default_factory=list)                  # compose
    frames: list[str] = Field(default_factory=list)                    # derive: asset ids, in order
    frames_group: str | None = None                                    # derive: every asset in a group
    layout: Literal["grid", "pack"] = "pack"                            # derive
    cell: tuple[int, int] | None = None        # derive: draw/scale each frame to fit this box
    columns: int | None = Field(default=None, ge=1)                     # derive grid
    padding: int = Field(default=2, ge=0)                                # derive: px between frames
    extrude: int = Field(default=0, ge=0, le=8)                          # derive: repeat edge pixels
    trim: bool | None = None                    # derive: crop transparent borders (default: pack only)
    animation: Animation | None = None                                   # derive: frames play in order

    @field_validator("source", "template")
    @classmethod
    def _paths(cls, v: str | None) -> str | None:
        return _recipe_path(v)

    def merged_over(self, base: "BuildSpec | None") -> "BuildSpec":
        """This asset's build on top of its group's defaults (params merge, fields override)."""
        if base is None:
            return self
        set_ = self.model_fields_set
        pick = {k: getattr(self if k in set_ else base, k) for k in type(self).model_fields if k != "params"}
        return BuildSpec(**pick, params={**base.params, **self.params})

    def problem(self) -> str | None:
        derive_set = bool(self.frames or self.frames_group or self.animation or self.cell or self.columns)
        if self.kind != "derive" and derive_set:
            return "frames, frames_group, cell, columns and animation belong to kind 'derive'"
        if self.kind == "svg":
            if self.layers or self.background:
                return "layers and background belong to kind 'compose'"
            if not (self.source or self.template):
                return "build needs a source, a template, or both"
        elif self.kind == "derive":
            if self.source or self.template or self.layers or self.background:
                return "kind 'derive' packs frames; it takes no source, template, layers or background"
            if bool(self.frames) == bool(self.frames_group):
                return "kind 'derive' needs frames (asset ids) or frames_group, not both"
            if self.columns and self.layout != "grid":
                return "columns applies to layout: grid"
        else:
            if self.source or self.template:
                return "kind 'compose' uses layers, not source/template"
            if not self.layers:
                return "kind 'compose' needs at least one layer"
        return None


class GroupSpec(_Strict):
    """Defaults shared by every asset whose `group` names this entry."""

    build: BuildSpec | None = None


class AssetSpec(_Strict):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(pattern=ASSET_ID)
    class_: str = Field(alias="class")
    subject: str = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)
    destination: str
    hero: bool = False
    group: str | None = None
    references: list[str] = Field(default_factory=list)
    needs_human_finish: bool = False
    notes: str | None = None  # free text for the producer (e.g. the in-game title, points, hidden)
    overrides: dict[str, Any] = Field(default_factory=dict)
    build: BuildSpec | None = None

    @field_validator("destination")
    @classmethod
    def _relative(cls, v: str) -> str:
        p = PurePosixPath(v)
        if p.is_absolute() or ".." in p.parts or not p.name:
            raise ValueError("destination must be a relative file path without '..'")
        return v


class Style(_Strict):
    block: str | None = None
    palette: list[str] = Field(default_factory=list)
    # Named colours for recipes ({{tokens.gold}}). With no palette, the palette is their values.
    tokens: dict[str, str] = Field(default_factory=dict)
    backgrounds: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)

    @field_validator("palette", "backgrounds")
    @classmethod
    def _hexes(cls, v: list[str]) -> list[str]:
        _check_hexes(v)
        return v

    @field_validator("tokens")
    @classmethod
    def _tokens(cls, v: dict[str, str]) -> dict[str, str]:
        check_tokens(v)
        return v

    @model_validator(mode="after")
    def _palette_from_tokens(self) -> "Style":
        if self.tokens and not self.palette:
            self.palette = palette_of(self.tokens)
        else:
            tokens_in_palette(self.tokens, self.palette)
        return self


def check_tokens(tokens: dict[str, str]) -> None:
    import re

    for k, v in tokens.items():
        if not re.match(TOKEN_NAME, k):
            raise ValueError(f"token name '{k}' must start with a letter and use letters, digits, _ or -")
        _check_hexes([v])


def palette_of(tokens: dict[str, str]) -> list[str]:
    seen: dict[str, str] = {}
    for v in tokens.values():
        seen.setdefault(v.upper(), v)
    return list(seen.values())


def tokens_in_palette(tokens: dict[str, str], palette: list[str]) -> None:
    pal = {h.upper() for h in palette}
    off = {k: v for k, v in tokens.items() if v.upper() not in pal}
    if off:
        raise ValueError(f"token colours must be in the palette (or leave the palette out): {off}")


class Settings(_Strict):
    max_attempts: int = Field(default=3, ge=1)
    gate_threshold: int = Field(default=15, ge=1)
    lease_minutes: int = Field(default=30, ge=1)


class BriefManifest(_Strict):
    version: Literal[2]
    project: str = Field(min_length=1)
    direction: str = Field(min_length=1)
    style: Style = Field(default_factory=Style)
    settings: Settings = Field(default_factory=Settings)
    classes: dict[str, AssetClass] = Field(default_factory=dict)
    groups: dict[str, GroupSpec] = Field(default_factory=dict)
    assets: list[AssetSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> "BriefManifest":
        seen: set[str] = set()
        dests: dict[str, str] = {}
        for a in self.assets:
            if a.id in seen:
                raise ValueError(f"duplicate asset id '{a.id}'")
            seen.add(a.id)
            if a.destination in dests:
                raise ValueError(
                    f"assets '{dests[a.destination]}' and '{a.id}' share destination '{a.destination}'"
                )
            dests[a.destination] = a.id
            self.resolve_class(a)  # raises on unknown class or bad overrides
            group = self.groups.get(a.group) if a.group else None
            if group is not None and group.build is not None:
                a.build = a.build.merged_over(group.build) if a.build else group.build.model_copy(deep=True)
            if a.build is not None and (why := a.build.problem()):
                raise ValueError(f"asset '{a.id}': {why}")
        for a in self.assets:  # derive: a group of frames becomes its asset ids, in brief order
            b = a.build
            if b is not None and b.kind == "derive" and b.frames_group:
                b.frames = [x.id for x in self.assets if x.group == b.frames_group and x.id != a.id]
                if not b.frames:
                    raise ValueError(f"asset '{a.id}': frames_group '{b.frames_group}' has no other assets")
            if b is not None and len(set(b.frames)) != len(b.frames):
                raise ValueError(f"asset '{a.id}': a frame is listed twice (an atlas holds each frame once; "
                                 "repeat frames in animation.sequence)")
            if b is not None and b.animation and (extra := sorted(set(b.animation.sequence) - set(b.frames))):
                raise ValueError(f"asset '{a.id}': animation.sequence names {extra}, which are not frames")
        uses = {a.id: [ly.asset for ly in a.build.layers if ly.asset] + list(a.build.frames)
                for a in self.assets if a.build}
        for aid, deps in uses.items():
            for d in deps:
                if d not in seen:
                    raise ValueError(f"asset '{aid}': layer or frame asset '{d}' is not in the brief")
        for aid in uses:  # a compose asset can't (indirectly) contain itself
            stack, path = [aid], set()
            while stack:
                cur = stack.pop()
                for d in uses.get(cur, []):
                    if d == aid:
                        raise ValueError(f"asset '{aid}' contains itself through its layers or frames")
                    if d not in path:
                        path.add(d)
                        stack.append(d)
        return self

    def resolve_class(self, asset: AssetSpec) -> AssetClass:
        return resolve_class(asset.class_, asset.overrides, self.classes, asset.id)


def resolve_class(
    name: str,
    overrides: dict[str, Any],
    custom: dict[str, AssetClass],
    asset_id: str = "?",
) -> AssetClass:
    from artpipeline.presets import PRESETS

    if name in custom:
        base = custom[name].model_dump()
    elif name in PRESETS:
        base = PRESETS[name].model_dump()
    else:
        known = sorted(set(custom) | set(PRESETS))
        raise ValueError(f"asset '{asset_id}': unknown class '{name}'. Known classes: {known}")
    if not overrides:
        return AssetClass.model_validate(base)
    try:
        return AssetClass.model_validate(_deep_merge(base, overrides))
    except Exception as e:  # pydantic.ValidationError
        raise ValueError(f"asset '{asset_id}': invalid overrides: {e}") from e


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _check_hexes(values: list[str]) -> None:
    import re

    for h in values:
        if not re.match(HEX, h):
            raise ValueError(f"'{h}' is not a #RRGGBB colour")


class Provenance(_Strict):
    """Where an attempt came from. Recorded verbatim; drives reproducibility and rights questions."""

    route: Literal["code_native", "agent_app", "image_gen", "human"]
    tool: str = Field(min_length=1)
    model: str | None = None
    prompt: str | None = None
    seed: str | int | None = None
    references: list[str] = Field(default_factory=list)
    rights: str | None = None
    notes: str | None = None
