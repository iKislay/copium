"""CLI: visual analytics and reporting."""

from __future__ import annotations

import click
from pathlib import Path

from .main import main


@main.command("report")
@click.option("--format", "-f", type=click.Choice(["text", "html"]), default="text", help="Report format.")
@click.option("--output", "-o", type=click.Path(), help="Output file path.")
@click.option("--period", "-p", type=click.Choice(["hour", "day", "week", "month"]), default="day", help="Time period.")
def report(format: str, output: str | None, period: str) -> None:
    """Generate compression analytics report.

    \b
    Examples:
        copium report                Text report for today
        copium report -f html        HTML report
        copium report -o report.html Save to file
    """
    from copium.analytics import VisualAnalytics

    analytics = VisualAnalytics.from_metrics_db()

    if format == "html":
        content = analytics.generate_html_report()
        ext = ".html"
    else:
        content = analytics.generate_text_report()
        ext = ".txt"

    if output:
        path = Path(output)
        analytics.save_report(path, format)
        click.echo(f"Report saved to: {path}")
    else:
        click.echo(content)


@main.command("savings")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def savings(json_output: bool) -> None:
    """Show compression savings summary.

    \b
    Examples:
        copium savings          Show savings summary
        copium savings --json   Output as JSON
    """
    from copium.analytics import VisualAnalytics
    import json

    analytics = VisualAnalytics.from_metrics_db()

    if json_output:
        data = {
            "cost_before": analytics.data.cost_before,
            "cost_after": analytics.data.cost_after,
            "cost_saved": analytics.data.cost_saved,
            "token_distribution": analytics.data.token_distribution,
            "transform_savings": analytics.data.transform_savings,
        }
        click.echo(json.dumps(data, indent=2))
    else:
        click.echo(analytics.generate_text_report())
