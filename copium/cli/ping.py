"""CLI: `copium ping` — fast health check (§9b).

Exit 0 if proxy is running, exit 1 otherwise.

  $ copium ping          # silent; exit code only
  $ copium ping -v       # verbose output
  $ copium ping --json   # JSON with status, uptime, tokens saved today

Designed to be fast (< 100 ms) for use in shell prompts, scripts, and CI.
"""

from __future__ import annotations

import json
import sys

import click

from .main import main


def _probe(port: int, timeout: float = 1.0) -> dict | None:
    """Hit /livez; return JSON payload or None if proxy is unreachable."""
    try:
        import httpx
        r = httpx.get(f"http://127.0.0.1:{port}/livez", timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _savings_today(port: int) -> int:
    """Quick tokens-saved-today figure from SavingsTracker (offline)."""
    try:
        from copium.proxy.savings_tracker import SavingsTracker
        data = SavingsTracker().stats_preview()
        return int(data.get("display_session", {}).get("tokens_saved", 0))
    except Exception:
        return 0


@main.command("ping")
@click.option(
    "--port", "-p", default=8787, type=int, envvar="COPIUM_PORT", show_default=True,
    help="Proxy port to check.",
)
@click.option("--json", "as_json", is_flag=True, help="Output JSON status.")
@click.option("-v", "--verbose", is_flag=True, help="Verbose human-readable output.")
@click.option(
    "--timeout", default=1.0, type=float, show_default=True,
    help="Connection timeout in seconds.",
)
def ping(port: int, as_json: bool, verbose: bool, timeout: float) -> None:
    """Fast proxy health check — exit 0 if running, exit 1 otherwise (§9b).

    \b
    Examples:
        copium ping                 # silent; check exit code
        copium ping -v              # verbose status line
        copium ping --json          # JSON output
        copium ping || copium start # start if not running
    """
    health = _probe(port, timeout=timeout)
    running = health is not None

    if as_json:
        uptime = int(health.get("uptime_seconds", 0)) if health else 0
        tokens_today = _savings_today(port) if running else 0
        click.echo(
            json.dumps(
                {
                    "status": "running" if running else "stopped",
                    "port": port,
                    "uptime_s": uptime,
                    "version": health.get("version", "?") if health else None,
                    "tokens_saved_today": tokens_today,
                },
                indent=2,
            )
        )
        sys.exit(0 if running else 1)

    if verbose:
        if running:
            uptime = int(health.get("uptime_seconds", 0))
            h, m, s = uptime // 3600, (uptime % 3600) // 60, uptime % 60
            uptime_str = f"{h}h {m}m {s}s" if h else (f"{m}m {s}s" if m else f"{s}s")
            version = health.get("version", "?")
            click.echo(
                click.style("● ", fg="green") +
                click.style(f"Copium v{version} running on port {port}", bold=True) +
                f"  uptime {uptime_str}"
            )
        else:
            click.echo(
                click.style("○ ", fg="red") +
                click.style(f"Copium not running on port {port}", bold=True) +
                "  run: copium start"
            )

    sys.exit(0 if running else 1)
