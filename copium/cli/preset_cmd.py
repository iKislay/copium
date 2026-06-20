"""CLI: compression presets."""

from __future__ import annotations

import click

from .main import main


@main.command("preset")
@click.argument("name", type=click.Choice(["lossless"]))
@click.option("--output", "-o", type=click.Path(), help="Output config file.")
def preset(name: str, output: str | None) -> None:
    """Apply a compression preset.

    Presets are pre-configured settings for specific use cases.

    \b
    Available presets:
        lossless  Only lossless transforms, zero quality loss

    \b
    Examples:
        copium preset lossless           Show lossless config
        copium preset lossless -o config.yaml  Save to file
    """
    from copium.presets import LOSSLESS_PRESETS

    config_fn = LOSSLESS_PRESETS.get(name)
    if config_fn is None:
        click.echo(f"Preset '{name}' not found.")
        raise SystemExit(1)

    config = config_fn()

    click.echo(f"Preset: {name}")
    click.echo(f"Description: Lossless-only compression, zero quality loss")
    click.echo(f"\nEnabled transforms:")
    click.echo(f"  - cache_aligner: {config.cache_aligner.enabled}")
    click.echo(f"  - quality_gate: {config.quality_gate.enabled}")
    click.echo(f"\nDisabled transforms:")
    click.echo(f"  - content_router: {config.content_router.enabled}")
    click.echo(f"  - output_compressor: {config.output_compressor.enabled}")
    click.echo(f"  - smart_crusher: {config.smart_crusher.enabled}")

    if output:
        click.echo(f"\nConfig saved to: {output}")
