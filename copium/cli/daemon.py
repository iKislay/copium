"""Daemon-mode commands: copium start / restart / status.

Plan §4a — the "Always On" Problem.

These are thin, user-facing wrappers around the existing
``copium install`` machinery.  A developer should never have to think
about deployment manifests; they just type one word.

Note: ``copium stop`` lives in ``proxy.py`` (already existed there with
port-based process kill logic). The stop command in proxy.py has been
enhanced to also print a session summary (§10b).

Usage:
    copium start                    # start proxy in background
    copium start --port 9090        # start on a custom port
    copium restart                  # stop + start (picks up config changes)
    copium status                   # show running/stopped, uptime, savings

Design notes:
* A "default" deployment profile is used transparently so that the
  user-facing commands remain profile-agnostic.
* ``copium start`` auto-installs the profile if none exists yet, so
  the developer never needs to run ``copium install apply`` first.
* All proxy flags accepted by ``copium proxy`` can be forwarded via
  ``copium start`` (port, backend, preset, etc.).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import click

from copium.install.health import probe_json, probe_ready
from copium.install.models import (
    ConfigScope,
    InstallPreset,
    ProviderSelectionMode,
    RuntimeKind,
    SupervisorKind,
)
from copium.install.planner import build_manifest
from copium.install.runtime import (
    runtime_status,
    start_detached_agent,
    wait_ready,
)
from copium.install.state import load_manifest, save_manifest

from .main import main

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_DEFAULT_PROFILE = "default"
_DEFAULT_PORT = 8787
_DEFAULT_HOST = "127.0.0.1"


def _load_or_create_manifest(
    port: int = _DEFAULT_PORT,
    host: str = _DEFAULT_HOST,
    backend: str = "anthropic",
    preset: str | None = None,
    mode: str = "token",
    memory: bool = False,
    no_telemetry: bool = False,
) -> "copium.install.models.DeploymentManifest":  # noqa: F821 — forward ref for type checkers
    """Return the default manifest, creating it on first call."""
    from copium.install.models import DeploymentManifest  # local import to keep startup fast

    existing = load_manifest(_DEFAULT_PROFILE)
    if existing is not None:
        return existing

    manifest = build_manifest(
        profile=_DEFAULT_PROFILE,
        preset=InstallPreset.PERSISTENT_SERVICE.value,
        runtime_kind=RuntimeKind.PYTHON.value,
        scope=ConfigScope.USER.value,
        provider_mode=ProviderSelectionMode.AUTO.value,
        targets=[],
        port=port,
        backend=backend,
        anyllm_provider=None,
        region=None,
        proxy_mode=mode,
        memory_enabled=memory,
        telemetry_enabled=not no_telemetry,
        image="ghcr.io/iKislay/copium:latest",
    )
    # Override host in proxy_args when non-default
    if host != _DEFAULT_HOST:
        manifest.proxy_args = [
            arg if not arg.startswith("127.0.0.1") else host for arg in manifest.proxy_args
        ]
    if preset:
        manifest.proxy_args = [*manifest.proxy_args, "--preset", preset]

    save_manifest(manifest)
    return manifest


def _is_running(port: int = _DEFAULT_PORT) -> bool:
    """Quick liveness check without loading the manifest."""
    return probe_ready(f"http://{_DEFAULT_HOST}:{port}/readyz")


def _uptime_str(manifest: "copium.install.models.DeploymentManifest") -> str:  # noqa: F821
    """Return a human-readable uptime string, or '--' if unknown."""
    from copium.install.paths import pid_path

    pid_file = pid_path(_DEFAULT_PROFILE)
    if not pid_file.exists():
        return "--"
    try:
        pid = int(pid_file.read_text().strip())
        # /proc/<pid>/stat: field 22 is start time in clock ticks since boot
        with open(f"/proc/{pid}/stat") as f:
            stats = f.read().split()
        ticks = int(stats[21])
        clk_tck = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        with open("/proc/uptime") as f:
            boot_secs = float(f.read().split()[0])
        # uptime_secs = boot_secs - (ticks / clk_tck)
        uptime_secs = boot_secs - (time.time() - (time.time() - boot_secs + ticks / clk_tck))
        # Simpler: use mtime of the pid file as a proxy for start time
        raise ValueError("fallback to mtime")  # noqa: TRY301
    except Exception:
        # Fallback: pid file mtime
        try:
            elapsed = time.time() - pid_file.stat().st_mtime
        except Exception:
            return "--"
    h = int(elapsed // 3600)
    m = int((elapsed % 3600) // 60)
    s = int(elapsed % 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _print_status(verbose: bool = False) -> None:
    """Print a rich copium status block (§6b output style)."""
    manifest = load_manifest(_DEFAULT_PROFILE)
    port = manifest.port if manifest else _DEFAULT_PORT
    host_url = f"http://{_DEFAULT_HOST}:{port}"
    running = _is_running(port)

    click.echo()
    if running:
        click.secho(f"  ● Copium is running", fg="green", bold=True, nl=False)
        if manifest:
            uptime = _uptime_str(manifest)
            click.echo(f"  (port {port}, uptime {uptime})")
        else:
            click.echo()
    else:
        click.secho("  ○ Copium is not running", fg="red", bold=True)
        click.echo()
        click.secho("  Start it with:  copium start", fg="yellow")
        click.echo()
        return

    # ── savings summary ──────────────────────────────────────────────────
    try:
        from copium.proxy.savings_tracker import SavingsTracker

        tracker = SavingsTracker()
        data = tracker.stats_preview()
        session = data.get("display_session", {})
        lifetime = data.get("lifetime", {})

        def _fmt_tokens(n: int) -> str:
            if n >= 1_000_000:
                return f"{n / 1_000_000:.1f}M"
            if n >= 1_000:
                return f"{n / 1_000:.1f}K"
            return str(n)

        def _fmt_usd(v: float) -> str:
            return f"${v:.4f}" if v < 1 else f"${v:.2f}"

        click.echo()
        click.secho("  Today's savings", fg="cyan")
        click.echo("  " + "─" * 38)

        reqs = session.get("requests", 0)
        tok_saved = session.get("tokens_saved", 0)
        usd_saved = session.get("compression_savings_usd", 0.0)
        pct = session.get("savings_percent", 0.0)

        click.echo(f"  Requests proxied    {reqs:>10,}")
        click.echo(f"  Tokens saved        {_fmt_tokens(tok_saved):>10}  (avg {pct:.0f}% per request)")
        click.echo(f"  Est. cost saved     {_fmt_usd(usd_saved):>10}")

        if verbose:
            lt_reqs = lifetime.get("requests", 0)
            lt_tok = lifetime.get("tokens_saved", 0)
            lt_usd = lifetime.get("compression_savings_usd", 0.0)
            click.echo()
            click.secho("  All-time", fg="cyan")
            click.echo("  " + "─" * 38)
            click.echo(f"  Requests proxied    {lt_reqs:>10,}")
            click.echo(f"  Tokens saved        {_fmt_tokens(lt_tok):>10}")
            click.echo(f"  Est. cost saved     {_fmt_usd(lt_usd):>10}")
    except Exception:
        pass  # savings tracker not yet populated — that's fine

    # ── config / paths ───────────────────────────────────────────────────
    click.echo()
    copium_dir = Path.home() / ".copium"
    config_file = copium_dir / "config.toml"
    log_file = copium_dir / "logs" / "copium.log"

    if config_file.exists():
        click.secho(f"  Config:    {config_file}", dim=True)
    click.secho(f"  Logs:      {log_file}", dim=True)
    click.secho(f"  Dashboard: {host_url}/dashboard", dim=True)
    click.echo()


# ---------------------------------------------------------------------------
# copium start
# ---------------------------------------------------------------------------


@main.command("start")
@click.option(
    "--port",
    "-p",
    default=_DEFAULT_PORT,
    type=int,
    envvar="COPIUM_PORT",
    show_default=True,
    help="Port to run the proxy on.",
)
@click.option(
    "--backend",
    default="anthropic",
    envvar="COPIUM_BACKEND",
    show_default=True,
    help="API backend (anthropic, bedrock, openrouter, …).",
)
@click.option(
    "--preset",
    default=None,
    type=click.Choice(["minimal", "standard", "aggressive", "local-llm", "lossless"]),
    envvar="COPIUM_PRESET",
    help="Named compression preset.",
)
@click.option(
    "--mode",
    default="token",
    type=click.Choice(["token", "cache"]),
    envvar="COPIUM_MODE",
    show_default=True,
    help="Optimization mode: token (max savings) or cache (prefix-cache friendly).",
)
@click.option("--memory", is_flag=True, help="Enable persistent memory.")
@click.option("--no-telemetry", is_flag=True, help="Disable anonymous telemetry.")
@click.option(
    "--wait/--no-wait",
    default=True,
    show_default=True,
    help="Wait for the proxy to be ready before returning.",
)
def start(
    port: int,
    backend: str,
    preset: str | None,
    mode: str,
    memory: bool,
    no_telemetry: bool,
    wait: bool,
) -> None:
    """Start the Copium proxy as a background daemon.

    \b
    The proxy runs detached from the terminal — it survives shell exit.
    Use `copium stop` to shut it down, `copium status` to check health.

    \b
    Examples:
        copium start                  Start proxy on default port (8787)
        copium start --port 9090      Start on port 9090
        copium start --preset aggressive  Start with aggressive compression
        copium start --memory         Enable persistent memory
    """
    if _is_running(port):
        click.secho(f"  ⚠  Copium is already running on port {port}.", fg="yellow")
        click.secho("     Use `copium restart` to restart, `copium status` to check.", dim=True)
        return

    click.echo()
    click.secho("  Starting Copium proxy…", bold=True)

    manifest = _load_or_create_manifest(
        port=port,
        backend=backend,
        preset=preset,
        mode=mode,
        memory=memory,
        no_telemetry=no_telemetry,
    )

    try:
        start_detached_agent(manifest.profile)
    except Exception as exc:
        click.secho(f"  ✗  Failed to launch proxy: {exc}", fg="red", err=True)
        raise SystemExit(1) from None

    if wait:
        click.echo("  Waiting for proxy to become ready…", nl=False)
        ready = wait_ready(manifest, timeout_seconds=30)
        if not ready:
            click.echo()
            click.secho(
                "  ✗  Proxy did not become ready in 30 seconds.\n"
                "     Check logs: copium logs",
                fg="red",
                err=True,
            )
            raise SystemExit(1)
        click.echo()

    click.secho(f"  ✓  Copium is running on port {port}", fg="green", bold=True)
    click.echo()
    click.secho("  View savings:   copium status", dim=True)
    click.secho("  Live dashboard: copium tui", dim=True)
    click.secho("  Stop proxy:     copium stop", dim=True)
    click.echo()


# ---------------------------------------------------------------------------
# copium restart
# ---------------------------------------------------------------------------


@main.command("restart")
@click.option(
    "--port",
    "-p",
    default=_DEFAULT_PORT,
    type=int,
    envvar="COPIUM_PORT",
    show_default=True,
    help="Port the proxy is running on.",
)
def restart(port: int) -> None:
    """Restart the Copium background daemon.

    Picks up any configuration changes made since the last start.

    \b
    Examples:
        copium restart            Restart the default proxy
    """
    manifest = load_manifest(_DEFAULT_PROFILE)

    click.echo()
    click.secho("  Restarting Copium…", bold=True)

    if manifest and _is_running(port):
        try:
            stop_runtime(manifest)
        except Exception as exc:
            click.secho(f"  ✗  Error stopping proxy: {exc}", fg="red", err=True)
            raise SystemExit(1) from None
        click.secho("  ✓  Stopped.", fg="green")
        time.sleep(1)

    if manifest is None:
        manifest = _load_or_create_manifest(port=port)

    try:
        start_detached_agent(manifest.profile)
    except Exception as exc:
        click.secho(f"  ✗  Failed to launch proxy: {exc}", fg="red", err=True)
        raise SystemExit(1) from None

    ready = wait_ready(manifest, timeout_seconds=30)
    if not ready:
        click.secho(
            "  ✗  Proxy did not become ready in 30 seconds.\n"
            "     Check logs: copium logs",
            fg="red",
            err=True,
        )
        raise SystemExit(1)

    click.secho(f"  ✓  Copium restarted on port {port}.", fg="green")
    click.echo()


# ---------------------------------------------------------------------------
# copium status
# ---------------------------------------------------------------------------


@main.command("status")
@click.option(
    "--port",
    "-p",
    default=_DEFAULT_PORT,
    type=int,
    envvar="COPIUM_PORT",
    show_default=True,
    help="Port the proxy should be running on.",
)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.option("--verbose", "-v", is_flag=True, help="Show all-time stats alongside session stats.")
def status(port: int, as_json: bool, verbose: bool) -> None:
    """Show Copium proxy health, uptime, and savings.

    \b
    Examples:
        copium status                 Compact status view
        copium status --verbose       Include all-time stats
        copium status --json          Machine-readable output
    """
    import json as _json

    manifest = load_manifest(_DEFAULT_PROFILE)
    running = _is_running(port)

    if as_json:
        payload: dict = {
            "status": "running" if running else "stopped",
            "port": port,
        }
        if manifest:
            payload["profile"] = manifest.profile
            payload["backend"] = manifest.backend
            payload["supervisor"] = manifest.supervisor_kind
        try:
            from copium.proxy.savings_tracker import SavingsTracker

            tracker = SavingsTracker()
            data = tracker.stats_preview()
            payload["savings"] = {
                "session": data.get("display_session", {}),
                "lifetime": data.get("lifetime", {}),
            }
        except Exception:
            payload["savings"] = None
        click.echo(_json.dumps(payload, indent=2))
        return

    _print_status(verbose=verbose)
