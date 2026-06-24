"""Command to tail Copium proxy logs."""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

import click

from . import console


def _get_log_path() -> Path:
    """Get the default log file path."""
    return Path.home() / ".copium" / "logs" / "copium.log"


@click.command()
@click.option(
    "--tail",
    "-n",
    default=100,
    show_default=True,
    help="Number of lines to show from the end.",
)
@click.option(
    "--follow",
    "-f",
    is_flag=True,
    help="Follow log output (like tail -f).",
)
@click.option(
    "--level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    default=None,
    help="Filter by log level.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def logs(tail: int, follow: bool, level: str | None, as_json: bool) -> None:
    """Tail Copium proxy logs.

    Shows recent log entries from the Copium proxy. Use --follow to watch
    logs in real time (Ctrl+C to stop).

    \b
    Examples:
        copium logs              Show last 100 lines
        copium logs -n 50        Show last 50 lines
        copium logs -f           Follow logs in real time
        copium logs --level ERROR  Show only errors
    """
    log_path = _get_log_path()

    if not log_path.exists():
        console.print(f"[yellow]⚠[/yellow] No log file found at {log_path}")
        console.print(
            "[dim]Start the proxy with [bold]copium start[/bold] to generate logs.[/dim]"
        )
        raise SystemExit(1)

    if follow:
        _follow_log(log_path, level)
    else:
        _tail_log(log_path, tail, level, as_json)


def _tail_log(path: Path, n: int, level: str | None, as_json: bool) -> None:
    """Show the last N lines of a log file."""
    try:
        lines = path.read_text().splitlines()
    except Exception as exc:
        console.print(f"[red]✗[/red] Failed to read log file: {exc}")
        raise SystemExit(1)

    # Filter by level if specified
    if level:
        level_upper = level.upper()
        lines = [l for l in lines if level_upper in l.upper()]

    # Show last N lines
    recent = lines[-n:]

    if as_json:
        import json

        click.echo(json.dumps({"lines": recent, "total": len(lines)}))
        return

    if not recent:
        console.print("[dim]No matching log entries.[/dim]")
        return

    for line in recent:
        click.echo(line)


def _follow_log(path: Path, level: str | None) -> None:
    """Follow a log file (like tail -f)."""
    console.print(f"[dim]Following {path} (Ctrl+C to stop)...[/dim]")

    # Handle Ctrl+C gracefully
    def _handle_sigint(sig: int, frame: object) -> None:
        console.print("\n[dim]Stopped following logs.[/dim]")
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _handle_sigint)

    try:
        with open(path) as f:
            # Seek to end
            f.seek(0, 2)

            while True:
                line = f.readline()
                if line:
                    if level:
                        if level.upper() in line.upper():
                            click.echo(line.rstrip())
                    else:
                        click.echo(line.rstrip())
                else:
                    import time

                    time.sleep(0.1)
    except Exception as exc:
        console.print(f"[red]✗[/red] Error following log: {exc}")
        raise SystemExit(1)
