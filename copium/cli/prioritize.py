"""CLI: git-aware file prioritization for codebase ingestion."""

from __future__ import annotations

import json

import click

from .main import main


@main.command("prioritize")
@click.option("--top", "-n", default=20, type=int, help="Show top N files.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
@click.option("--max-commits", default=5000, type=int, help="Max commits to analyze.")
@click.option("--max-days", default=365, type=int, help="Max days back to analyze.")
@click.pass_context
def prioritize(
    ctx: click.Context,
    top: int,
    json_output: bool,
    max_commits: int,
    max_days: int,
) -> None:
    """Rank files by git history importance for codebase ingestion.

    Uses commit frequency, recency, author match, branch relevance,
    and dependency centrality to score files. Higher score = more
    important for an LLM to understand.

    \b
    Examples:
        copium prioritize           Show top 20 files
        copium prioritize -n 50     Show top 50 files
        copium prioritize --json    Output as JSON
    """
    from copium.graph.git_prioritize import (
        GitPrioritizationConfig,
        prioritize_files,
    )

    config = GitPrioritizationConfig(
        max_commits_to_analyze=max_commits,
        max_days_back=max_days,
    )

    click.echo("Analyzing git history...", err=True)
    results = prioritize_files(config=config)

    if not results:
        click.echo("No git history found or not in a git repository.")
        return

    top_results = results[:top]

    if json_output:
        output = [
            {"path": path, "score": score, "signals": signals}
            for path, score, signals in top_results
        ]
        click.echo(json.dumps(output, indent=2))
    else:
        click.echo(f"\nTop {len(top_results)} files by git importance:\n")
        click.echo(f"{'Rank':<6}{'Score':<8}{'File':<50}{'Signals'}")
        click.echo("-" * 120)
        for i, (path, score, signals) in enumerate(top_results, 1):
            sig_str = (
                f"freq={signals['commit_frequency']:.2f} "
                f"rec={signals['recency']:.2f} "
                f"auth={signals['author_match']:.2f} "
                f"br={signals['branch_relevance']:.2f}"
            )
            click.echo(f"{i:<6}{score:<8.4f}{path:<50}{sig_str}")

        click.echo(f"\n({len(results)} total files analyzed)")
