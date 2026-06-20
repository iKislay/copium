"""CLI: live TUI dashboard showing compression savings in real-time.

Uses rich to display a live-updating terminal dashboard with:
- Tokens saved / dollars saved
- Per-transform breakdown
- Cache hit rate
- Live request stream
- Pipeline timing
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import click

from .main import main


def _load_stats(db_path: Path | None = None) -> dict:
    """Load stats from the SQLite metrics database."""
    if db_path is None:
        from copium.paths import workspace_dir

        db_path = workspace_dir() / "metrics.db"

    if not db_path.exists():
        return {}

    try:
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # Get aggregate stats
        row = conn.execute(
            """
            SELECT
                COUNT(*) as total_requests,
                SUM(tokens_before) as total_tokens_before,
                SUM(tokens_after) as total_tokens_after,
                AVG(CASE WHEN tokens_before > 0
                    THEN (tokens_before - tokens_after) * 100.0 / tokens_before
                    ELSE 0 END) as avg_savings_pct,
                AVG(duration_ms) as avg_latency_ms
            FROM request_metrics
            WHERE timestamp > datetime('now', '-1 hour')
            """
        ).fetchone()

        # Get per-transform stats
        transforms = conn.execute(
            """
            SELECT transform, COUNT(*) as count
            FROM transform_applied
            WHERE timestamp > datetime('now', '-1 hour')
            GROUP BY transform
            ORDER BY count DESC
            LIMIT 10
            """
        ).fetchall()

        # Get cache hit rate
        cache_row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN cached = 1 THEN 1 ELSE 0 END) as hits,
                COUNT(*) as total
            FROM request_metrics
            WHERE timestamp > datetime('now', '-1 hour')
            """
        ).fetchone()

        conn.close()

        return {
            "total_requests": row["total_requests"] or 0,
            "tokens_before": row["total_tokens_before"] or 0,
            "tokens_after": row["total_tokens_after"] or 0,
            "tokens_saved": (row["total_tokens_before"] or 0) - (row["total_tokens_after"] or 0),
            "avg_savings_pct": row["avg_savings_pct"] or 0,
            "avg_latency_ms": row["avg_latency_ms"] or 0,
            "transforms": [{"name": t["transform"], "count": t["count"]} for t in transforms],
            "cache_hits": cache_row["hits"] or 0,
            "cache_total": cache_row["total"] or 0,
            "cache_hit_rate": (
                (cache_row["hits"] / cache_row["total"] * 100) if cache_row["total"] else 0
            ),
        }
    except Exception:
        return {}


def _format_tokens(n: int) -> str:
    """Format token count with K/M suffix."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _format_cost(tokens: int, model: str = "gpt-4o") -> str:
    """Estimate cost in dollars."""
    # Rough average: $3/M input tokens
    return f"${tokens * 3 / 1_000_000:.4f}"


def _render_dashboard(stats: dict) -> str:
    """Render the dashboard as a rich-formatted string."""
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.columns import Columns
    from rich.text import Text
    from io import StringIO

    output = StringIO()
    console = Console(file=output, width=100)

    # Header
    console.print()
    console.print(
        Panel(
            "[bold cyan]Copium Live Dashboard[/bold cyan]  "
            "[dim]Press Ctrl+C to exit[/dim]",
            style="cyan",
        )
    )

    if not stats:
        console.print("[yellow]No data yet. Waiting for requests...[/yellow]")
        return output.getvalue()

    # Stats cards
    tokens_saved = stats.get("tokens_saved", 0)
    total_requests = stats.get("total_requests", 0)
    avg_savings = stats.get("avg_savings_pct", 0)
    cache_rate = stats.get("cache_hit_rate", 0)
    avg_latency = stats.get("avg_latency_ms", 0)

    stats_table = Table(show_header=False, box=None, padding=(0, 2))
    stats_table.add_column(style="bold")
    stats_table.add_column()

    stats_table.add_row("Requests", f"[green]{total_requests:,}[/green]")
    stats_table.add_row("Tokens Saved", f"[bold green]{_format_tokens(tokens_saved)}[/bold green]")
    stats_table.add_row("Cost Saved", f"[bold yellow]{_format_cost(tokens_saved)}[/bold yellow]")
    stats_table.add_row("Avg Savings", f"[cyan]{avg_savings:.1f}%[/cyan]")
    stats_table.add_row("Cache Hit Rate", f"[magenta]{cache_rate:.1f}%[/magenta]")
    stats_table.add_row("Avg Latency", f"[blue]{avg_latency:.0f}ms[/blue]")

    console.print(Panel(stats_table, title="[bold]Summary (last hour)[/bold]", border_style="green"))

    # Transform breakdown
    transforms = stats.get("transforms", [])
    if transforms:
        t_table = Table(title="Transform Breakdown", border_style="blue")
        t_table.add_column("Transform", style="cyan")
        t_table.add_column("Count", justify="right", style="green")

        for t in transforms[:8]:
            t_table.add_row(t["name"], str(t["count"]))

        console.print(t_table)

    return output.getvalue()


@click.command(name="dashboard")
@click.option("--watch", "-w", is_flag=True, help="Live-updating dashboard (refreshes every 2s).")
@click.option("--interval", default=2, type=int, help="Refresh interval in seconds.")
@click.option("--json-output", is_flag=True, help="Output stats as JSON.")
def dashboard(watch: bool, interval: int, json_output: bool) -> None:
    """Live terminal dashboard showing compression savings.

    \b
    Examples:
        copium dashboard          One-shot stats display
        copium dashboard -w       Live-updating dashboard
        copium dashboard --json   Output as JSON
    """
    if watch and json_output:
        click.echo("Cannot use --watch with --json-output.", err=True)
        raise SystemExit(1)

    if json_output:
        stats = _load_stats()
        click.echo(json.dumps(stats, indent=2, default=str))
        return

    if not watch:
        stats = _load_stats()
        click.echo(_render_dashboard(stats))
        return

    # Live mode
    try:
        from rich.console import Console

        console = Console()
        with console.screen() as screen:
            while True:
                stats = _load_stats()
                output = _render_dashboard(stats)
                screen.clear()
                screen.print(output)
                time.sleep(interval)
    except KeyboardInterrupt:
        pass


# Register as a subcommand
@main.group(invoke_without_command=True)
@click.pass_context
def tui(ctx: click.Context) -> None:
    """Terminal UI dashboard for live compression stats."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(dashboard)


tui.add_command(dashboard, "dashboard")
