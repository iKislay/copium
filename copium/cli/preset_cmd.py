"""CLI: compression presets."""

from __future__ import annotations

import click

from .main import main


@main.command("preset")
@click.argument(
    "name",
    type=click.Choice(["lossless", "minimal", "standard", "aggressive", "local-llm"]),
)
@click.option("--output", "-o", type=click.Path(), help="Output config file.")
@click.option("--describe", is_flag=True, help="Show what the preset enables/disables.")
def preset(name: str, output: str | None, describe: bool) -> None:
    """Apply or inspect a named compression preset.

    Presets are pre-configured settings for specific use cases.

    \b
    Available presets:
        minimal     Only structural transforms; safe and fast
        standard    Full compression stack; recommended for most users
        aggressive  Maximum savings; more aggressive settings
        local-llm   Optimized for Ollama/VLLM/llama.cpp local models
        lossless    Only lossless transforms; zero quality loss

    \b
    Examples:
        copium preset standard           Show standard preset config
        copium preset aggressive -o config.yaml
        copium proxy --preset aggressive  Start proxy with aggressive preset
    """
    from copium.presets import ALL_PRESETS, PRESET_DESCRIPTIONS

    config_fn = ALL_PRESETS.get(name)
    if config_fn is None:
        click.echo(f"Preset '{name}' not found.")
        raise SystemExit(1)

    description = PRESET_DESCRIPTIONS.get(name, "")
    click.echo(f"Preset: {name}")
    click.echo(f"Description: {description}")

    if describe or True:  # Always show details
        config = config_fn()
        click.echo("\nKey settings:")
        click.echo(f"  cache_aligner     : {'on' if config.cache_aligner.enabled else 'off'}")
        click.echo(
            f"  smart_crusher     : {'on' if config.smart_crusher.enabled else 'off'}"
            + (
                f"  (max_items={config.smart_crusher.max_items_after_crush})"
                if config.smart_crusher.enabled
                else ""
            )
        )
        click.echo(
            f"  output_compressor : {'on' if config.output_compressor.enabled else 'off'}"
        )
        click.echo(
            f"  session_dedup     : {'on' if config.session_dedup.enabled else 'off'}"
        )
        click.echo(
            f"  differential_resp : {'on' if config.differential_response.enabled else 'off'}"
        )
        click.echo(
            f"  error_compressor  : {'on' if config.error_compressor.enabled else 'off'}"
        )
        click.echo(f"  quality_gate      : {'on' if config.quality_gate.enabled else 'off'}")

    click.echo(
        "\nTip: Start the proxy with this preset using:\n"
        f"  copium proxy --preset {name}"
    )

    if output:
        click.echo(f"\nConfig saved to: {output}")
