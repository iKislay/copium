"""CLI: copium stats — quick savings summary.

Prints a compact snapshot of proxy compression savings without launching
the full web dashboard. Useful for quick terminal checks.

Usage:
    copium stats                     # Last 24h summary
    copium stats --period 7d         # Last 7 days
    copium stats --period all        # All-time
    copium stats --json              # Machine-readable JSON
"""

from __future__ import annotations

import json
import sys
from typing import Any

import click

from .main import main


def _format_tokens(n: int) -> str:
    """Format a token count with human-readable suffixes."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _format_usd(v: float) -> str:
    """Format a USD value with appropriate precision."""
    if v >= 100:
        return f"${v:.0f}"
    if v >= 1:
        return f"${v:.2f}"
    return f"${v:.4f}"


def _fetch_stats() -> dict[str, Any] | None:
    """Read the savings tracker state from disk without starting the proxy."""
    try:
        from copium.proxy.savings_tracker import SavingsTracker

        tracker = SavingsTracker()
        return tracker.stats_preview()
    except Exception:
        return None


def _print_stats(data: dict[str, Any], period: str) -> None:
    """Render stats in a compact, coloured terminal format."""
    lifetime = data.get("lifetime", {})
    session = data.get("display_session", {})

    tokens_saved_lifetime = lifetime.get("tokens_saved", 0)
    usd_saved_lifetime = lifetime.get("compression_savings_usd", 0.0)
    requests_lifetime = lifetime.get("requests", 0)

    # Session stats
    tokens_saved_session = session.get("tokens_saved", 0)
    usd_saved_session = session.get("compression_savings_usd", 0.0)
    requests_session = session.get("requests", 0)
    savings_pct = session.get("savings_percent", 0.0)

    # Projects breakdown
    projects: dict[str, Any] = data.get("projects", {})

    click.echo()
    click.secho("  Copium Savings Report", bold=True)
    click.echo("  " + "─" * 42)

    if period in ("session", "current"):
        click.secho("  Current Session", fg="cyan", bold=True)
        click.echo(f"  Requests   : {requests_session:,}")
        click.echo(f"  Tokens saved: {_format_tokens(tokens_saved_session)}")
        click.echo(f"  Cost saved  : {_format_usd(usd_saved_session)}")
        click.echo(f"  Compression : {savings_pct:.1f}%")
    else:
        click.secho("  All-Time Lifetime", fg="cyan", bold=True)
        click.echo(f"  Requests   : {requests_lifetime:,}")
        click.echo(f"  Tokens saved: {_format_tokens(tokens_saved_lifetime)}")
        click.echo(f"  Cost saved  : {_format_usd(usd_saved_lifetime)}")

        if requests_lifetime > 0 and tokens_saved_lifetime > 0:
            total_input = lifetime.get("total_input_tokens", 0)
            if total_input > 0:
                pct = tokens_saved_lifetime / (tokens_saved_lifetime + total_input) * 100
                click.echo(f"  Compression : {pct:.1f}%")

    # Top projects
    if projects:
        click.echo()
        click.secho("  Top Projects", fg="cyan", bold=True)
        for i, (name, pdata) in enumerate(list(projects.items())[:5]):
            saved = _format_tokens(pdata.get("tokens_saved", 0))
            pct = pdata.get("savings_percent", 0.0)
            click.echo(f"  {i + 1}. {name[:30]:<30} {saved:>6} tokens  ({pct:.0f}% saved)")

    # Recent history count
    history_points = data.get("history_points", 0)
    storage_path = data.get("storage_path", "")
    click.echo()
    click.echo(f"  History    : {history_points:,} data points")
    if storage_path:
        click.echo(f"  Storage    : {storage_path}")
    click.echo()
    click.secho(
        "  Tip: Run `copium proxy` to start the proxy, "
        "`copium dashboard` to open the web UI.",
        dim=True,
    )
    click.echo()


@main.command("stats")
@click.option(
    "--period",
    "-p",
    default="all",
    type=click.Choice(["all", "session", "current"]),
    help="Time period to summarise (default: all)",
    show_default=True,
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output raw JSON (machine-readable)",
)
def stats(period: str, as_json: bool) -> None:
    """Show a quick compression savings summary.

    \b
    Examples:
        copium stats                  # All-time summary
        copium stats --period session # Current session only
        copium stats --json           # Machine-readable output
    """
    data = _fetch_stats()

    if data is None:
        click.secho(
            "No savings data found. Start the proxy with `copium proxy` "
            "and send some requests first.",
            fg="yellow",
            err=True,
        )
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(data, indent=2))
        return

    _print_stats(data, period)
