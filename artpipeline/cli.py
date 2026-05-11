import click


@click.group()
@click.option("--human", is_flag=True, help="Human-readable output (dev only)")
@click.pass_context
def main(ctx, human):
    ctx.ensure_object(dict)
    ctx.obj["human"] = human
