import json
import shutil
from dataclasses import asdict
from pathlib import Path

import click

from artpipeline import manifest, parser
from artpipeline import review as review_mod


def _emit(data: dict, human: bool) -> None:
    if human:
        click.echo(json.dumps(data, indent=2))
    else:
        click.echo(json.dumps(data))


def _load_pipeline():
    path = Path("pipeline.json")
    if not path.exists():
        raise click.ClickException(
            "pipeline.json not found. Run 'artpipeline parse <brief>' first."
        )
    return manifest.load(path), path


_NEXT_COMMANDS = {
    "pending": "artpipeline prompt {id}",
    "prompted": "artpipeline file <downloaded-image> {id}",
    "filed": "artpipeline review {id}",
    "rejected": "artpipeline prompt {id} --retry",
}

_EXPECTED_EXTENSIONS = {
    "bird_sprite": ".png",
    "app_icon": ".png",
    "ui_glyph": ".svg",
}

# Background-removal thresholds (per channel, 0-255).
# Used by _process_source_image when an asset has transparent_background=True.
# Pixels with min(R,G,B) >= _BG_OPAQUE_MAX are fully transparent.
# Pixels in [_BG_FEATHER_MIN, _BG_OPAQUE_MAX) get a linear-ramp alpha so anti-aliased
# silhouette edges don't show a hard halo.
_BG_OPAQUE_MAX = 240
_BG_FEATHER_MIN = 200


def _process_source_image(source_path, dest_path,
                          canonical_dims, remove_background):
    """Resize source -> canonical and optionally key out near-white background.

    Returns True if Pillow was available and the image was processed; False if
    Pillow is not installed (caller should fall back to plain copy).
    """
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        return False

    resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
    try:
        with Image.open(source_path) as src:
            img = src.copy()
    except (UnidentifiedImageError, OSError):
        # Source is not a decodable image; let caller fall back to plain copy.
        return False

    target_size = tuple(canonical_dims)
    if tuple(img.size) != target_size:
        img = img.resize(target_size, resample)

    if remove_background:
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        px = img.load()
        w, h = img.size
        opaque_max = _BG_OPAQUE_MAX
        feather_min = _BG_FEATHER_MIN
        feather_range = opaque_max - feather_min
        for y in range(h):
            for x in range(w):
                r, g, b, a = px[x, y]
                m = min(r, g, b)
                if m >= opaque_max:
                    px[x, y] = (r, g, b, 0)
                elif m >= feather_min:
                    new_a = int(round((opaque_max - m) * 255 / feather_range))
                    if new_a < a:
                        px[x, y] = (r, g, b, new_a)

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest_path)
    return True


@click.group()
@click.option("--human", is_flag=True, help="Human-readable output (dev only)")
@click.pass_context
def main(ctx, human):
    ctx.ensure_object(dict)
    ctx.obj["human"] = human


@main.command()
@click.argument("brief", type=click.Path(exists=True, path_type=Path))
@click.pass_context
def parse(ctx, brief):
    """Parse an art brief and create pipeline.json."""
    try:
        raw = parser.parse_brief(brief)
    except ValueError as e:
        raise click.ClickException(str(e))

    pipeline_path = brief.parent / "pipeline.json"

    existing = {}
    if pipeline_path.exists():
        try:
            existing_manifest = manifest.load(pipeline_path)
            existing = existing_manifest.assets
        except (ValueError, KeyError, TypeError) as e:
            click.echo(f"Warning: could not read existing pipeline.json ({e}), starting fresh.", err=True)

    assets = {}
    for entry in raw.get("assets", []):
        asset_id = entry["id"]
        if asset_id in existing:
            assets[asset_id] = existing[asset_id]
        else:
            dr = entry.get("derived_resolutions")
            if dr:
                dr = {
                    k: {**v, "filed_path": v.get("filed_path")}
                    for k, v in dr.items()
                }
            assets[asset_id] = manifest.Asset(
                id=asset_id,
                status="pending",
                type=entry["type"],
                destination=entry["destination"],
                dimensions=entry["dimensions"],
                prompt=entry["prompt"],
                acceptance_criteria=entry["acceptance_criteria"],
                species=entry.get("species"),
                derived_resolutions=dr,
                mockup_only=bool(entry.get("mockup_only", False)),
                transparent_background=bool(entry.get("transparent_background", False)),
            )

    m = manifest.Manifest(
        brief=brief.name,
        project=raw["project"],
        direction=raw["direction"],
        assets=assets,
    )
    manifest.save(m, pipeline_path)

    output = {
        "project": m.project,
        "direction": m.direction,
        "pipeline": str(pipeline_path),
        "assets": [
            {"id": a.id, "type": a.type, "status": a.status}
            for a in m.assets.values()
        ],
    }
    _emit(output, ctx.obj["human"])


@main.command()
@click.option("--asset", default=None, help="Show a single asset by ID")
@click.pass_context
def status(ctx, asset):
    """Show pipeline status."""
    m, _ = _load_pipeline()
    human = ctx.obj["human"]

    if asset:
        try:
            a = m.get_asset(asset)
        except KeyError as e:
            raise click.ClickException(str(e))
        _emit(asdict(a), human)
        return

    grouped = {}
    for a in m.assets.values():
        grouped.setdefault(a.status, []).append({"id": a.id, "type": a.type})
    _emit(grouped, human)


@main.command(name="next")
@click.option(
    "--stage",
    default=None,
    type=click.Choice(["pending", "prompted", "filed", "approved", "rejected"]),
    help="Filter to assets at a specific status",
)
@click.pass_context
def next_cmd(ctx, stage):
    """Return the next asset needing action."""
    m, _ = _load_pipeline()

    for a in m.assets.values():
        if stage and a.status != stage:
            continue
        if a.status == "approved":
            continue
        cmd = _NEXT_COMMANDS.get(a.status, "artpipeline status --asset {id}").format(id=a.id)
        _emit({"asset_id": a.id, "status": a.status, "next_command": cmd}, ctx.obj["human"])
        return

    _emit({"asset_id": None, "message": "All assets approved."}, ctx.obj["human"])


@main.command()
@click.argument("asset_id")
@click.option("--retry", is_flag=True, help="Generate revised prompt using stored rejection reason")
@click.pass_context
def prompt(ctx, asset_id, retry):
    """Get the image-gen prompt for an asset."""
    m, pipeline_path = _load_pipeline()
    try:
        a = m.get_asset(asset_id)
    except KeyError as e:
        raise click.ClickException(str(e))

    text = a.prompt
    if retry:
        reason = a.rejection_reason or "no reason recorded"
        text = (
            "REVISION REQUEST: The previous attempt was rejected because: \"" + reason + "\".\n"
            "Please adjust accordingly.\n\n" + text
        )

    a.status = "prompted"
    manifest.save(m, pipeline_path)

    _emit({"asset_id": a.id, "prompt": text, "retry_count": a.retry_count}, ctx.obj["human"])


@main.command(name="file")
@click.argument("image_path", type=click.Path(path_type=Path))
@click.argument("asset_id")
@click.pass_context
def file_cmd(ctx, image_path, asset_id):
    """Copy a downloaded image to its pipeline destination."""
    if not image_path.exists():
        raise click.ClickException(f"Source file not found: {image_path}")

    m, pipeline_path = _load_pipeline()
    try:
        a = m.get_asset(asset_id)
    except KeyError as e:
        raise click.ClickException(str(e))

    if a.mockup_only:
        if image_path.suffix.lower() != ".png":
            raise click.ClickException(
                f"Mockup assets require a .png file; got '{image_path.suffix}'."
            )
    else:
        expected_ext = _EXPECTED_EXTENSIONS.get(a.type, ".png")
        if image_path.suffix.lower() != expected_ext:
            raise click.ClickException(
                f"Wrong file extension '{image_path.suffix}' for asset type '{a.type}'. "
                f"Expected '{expected_ext}'."
            )

    dest = pipeline_path.parent / a.destination
    dest.parent.mkdir(parents=True, exist_ok=True)

    raster_processed = False
    if not a.mockup_only and dest.suffix.lower() == ".png":
        raster_processed = _process_source_image(
            image_path, dest, a.dimensions, a.transparent_background
        )
    if not raster_processed:
        shutil.copy2(image_path, dest)

    a.filed_path = str(a.destination)

    if a.derived_resolutions:
        try:
            from PIL import Image
            resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
            with Image.open(dest) as img:
                for res_info in a.derived_resolutions.values():
                    res_dest = pipeline_path.parent / res_info["destination"]
                    res_dest.parent.mkdir(parents=True, exist_ok=True)
                    scaled = img.resize(tuple(res_info["dimensions"]), resample)
                    scaled.save(res_dest)
                    res_info["filed_path"] = res_info["destination"]
        except ImportError:
            pass

    a.status = "filed"
    manifest.save(m, pipeline_path)

    output = {"asset_id": a.id, "filed_path": a.filed_path}
    if a.derived_resolutions:
        derived = {k: v["filed_path"] for k, v in a.derived_resolutions.items() if v.get("filed_path")}
        if derived:
            output["derived_filed_paths"] = derived
    _emit(output, ctx.obj["human"])


@main.command()
@click.argument("asset_id")
@click.pass_context
def review(ctx, asset_id):
    """Run programmatic checks and surface acceptance criteria."""
    m, pipeline_path = _load_pipeline()
    try:
        a = m.get_asset(asset_id)
    except KeyError as e:
        raise click.ClickException(str(e))

    if a.status not in ("filed", "approved", "rejected"):
        raise click.ClickException(
            f"Asset '{asset_id}' has status '{a.status}' - it must be filed before review. "
            f"Run 'artpipeline file <image> {asset_id}' first."
        )

    file_path = pipeline_path.parent / a.destination
    effective_type = "mockup" if a.mockup_only else a.type
    checks = review_mod.run_checks(file_path, a.dimensions, effective_type)

    output = {
        "asset_id": a.id,
        "checks": checks,
        "acceptance_criteria": a.acceptance_criteria,
        "visual_review_required": True,
    }
    if a.mockup_only:
        output["is_mockup"] = True

    if a.derived_resolutions:
        derived_checks = {}
        for res_key, res_info in a.derived_resolutions.items():
            fp = res_info.get("filed_path")
            if fp:
                derived_checks[res_key] = review_mod.run_checks(
                    pipeline_path.parent / fp, res_info["dimensions"], a.type
                )
        if derived_checks:
            output["derived_checks"] = derived_checks

    _emit(output, ctx.obj["human"])


@main.command()
@click.argument("asset_id")
@click.pass_context
def approve(ctx, asset_id):
    """Mark an asset as approved."""
    m, pipeline_path = _load_pipeline()
    try:
        a = m.get_asset(asset_id)
    except KeyError as e:
        raise click.ClickException(str(e))
    a.status = "approved"
    manifest.save(m, pipeline_path)
    _emit({"asset_id": a.id, "status": a.status}, ctx.obj["human"])


@main.command()
@click.argument("asset_id")
@click.option("--reason", required=True, help="Why the asset was rejected (used in retry prompt)")
@click.pass_context
def reject(ctx, asset_id, reason):
    """Mark an asset as rejected and store the reason for retry."""
    m, pipeline_path = _load_pipeline()
    try:
        a = m.get_asset(asset_id)
    except KeyError as e:
        raise click.ClickException(str(e))
    a.status = "rejected"
    a.rejection_reason = reason
    a.retry_count += 1
    manifest.save(m, pipeline_path)
    _emit({"asset_id": a.id, "status": a.status, "retry_count": a.retry_count}, ctx.obj["human"])
