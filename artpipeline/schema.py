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


class BuildSpec(_Strict):
    """How artpipeline builds an asset itself (2.1). Paths are relative to the pipeline root.
    B1 supports kind 'svg': an SVG source and/or a shared template with <ap:slot/>, filled with
    params and the style's named colour tokens."""

    kind: Literal["svg"] = "svg"
    source: str | None = None
    template: str | None = None
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @field_validator("source", "template")
    @classmethod
    def _paths(cls, v: str | None) -> str | None:
        return _recipe_path(v)

    def merged_over(self, base: "BuildSpec | None") -> "BuildSpec":
        """This asset's build on top of its group's defaults (params merge, fields override)."""
        if base is None:
            return self
        set_ = self.model_fields_set
        return BuildSpec(
            kind=self.kind if "kind" in set_ else base.kind,
            source=self.source if "source" in set_ else base.source,
            template=self.template if "template" in set_ else base.template,
            params={**base.params, **self.params},
        )


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
            if a.build is not None and not (a.build.source or a.build.template):
                raise ValueError(f"asset '{a.id}': build needs a source, a template, or both")
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
