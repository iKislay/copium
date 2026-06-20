"""CLI: A/B benchmarking for compression configs."""

from __future__ import annotations

import json
import click
from pathlib import Path

from .main import main


@main.command("benchmark")
@click.argument("config_a", type=click.Path(exists=True))
@click.argument("config_b", type=click.Path(exists=True))
@click.option("--prompts", "-p", type=click.Path(exists=True), required=True, help="JSON file with test prompts.")
@click.option("--output", "-o", type=click.Path(), help="Output results file.")
@click.option("--name", default="ab-test", help="Test name.")
def benchmark(
    config_a: str,
    config_b: str,
    prompts: str,
    output: str | None,
    name: str,
) -> None:
    """Run A/B benchmark comparing two compression configs.

    \b
    Examples:
        copium benchmark config_a.yaml config_b.yaml -p prompts.json
        copium benchmark baseline.yaml optimized.yaml -p test.json -o results.json
    """
    from copium.benchmark import ABenchmarker, BenchmarkPrompt
    from copium.config import CopiumConfig
    import yaml

    # Load configs
    with open(config_a) as f:
        config_a_data = yaml.safe_load(f)
    with open(config_b) as f:
        config_b_data = yaml.safe_load(f)

    # Load prompts
    with open(prompts) as f:
        prompts_data = json.load(f)

    prompt_list = [
        BenchmarkPrompt(
            id=p.get("id", f"prompt-{i}"),
            messages=p["messages"],
            tools=p.get("tools"),
        )
        for i, p in enumerate(prompts_data)
    ]

    # Run benchmark
    benchmarker = ABenchmarker()
    config_a_obj = CopiumConfig(**config_a_data) if config_a_data else CopiumConfig()
    config_b_obj = CopiumConfig(**config_b_data) if config_b_data else CopiumConfig()

    test_config = benchmarker.create_test(
        name=name,
        config_a=config_a_obj,
        config_b=config_b_obj,
        prompts=prompt_list,
    )

    click.echo(f"Running A/B benchmark: {name}")
    click.echo(f"Config A: {config_a}")
    click.echo(f"Config B: {config_b}")
    click.echo(f"Prompts: {len(prompt_list)}")

    result = benchmarker.run_test(test_config)

    # Display results
    click.echo("\n" + "=" * 60)
    click.echo(f"Results: {result.test_name}")
    click.echo("=" * 60)
    click.echo(f"Winner: {result.winner}")
    click.echo(f"Total tokens saved: {result.total_tokens_saved:,}")
    click.echo(f"Total cost saved: ${result.total_cost_saved:.4f}")
    click.echo(f"Average savings: {result.avg_savings_percent:.1f}%")

    if output:
        benchmarker.export_results(result, Path(output))
        click.echo(f"\nResults exported to: {output}")
