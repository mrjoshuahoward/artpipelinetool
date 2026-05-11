import json
import sys
from pathlib import Path

import click

from artpipeline import manifest, parser


def _emit(data: dict, human: bool) -> None:
    if human:
        click.echo(json.dumps(data, indent=2))
    else:
        click.echo(json.dumps(data))


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
            assets[asset_id] = manifest.Asset(
                id=asset_id,
                status="pending",
                type=entry["type"],
                destination=entry["destination"],
                dimensions=entry["dimensions"],
                prompt=entry["prompt"],
                acceptance_criteria=entry["acceptance_criteria"],
                species=entry.get("species"),
                resolution=entry.get("resolution"),
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
