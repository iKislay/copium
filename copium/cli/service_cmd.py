"""System service management: copium service install/remove/status/logs.

Plan §4b — System Service Integration.

Allows Copium to run as a system service that auto-starts on login,
so the proxy is always available before the developer even opens a
terminal.

Supported platforms:
  Linux:   systemd --user unit (default) or system unit with --scope system
  macOS:   launchd LaunchAgent (~/Library/LaunchAgents/)
  Windows: Windows Service (sc.exe) or Task Scheduler

Usage:
    copium service install          Install & enable autostart service
    copium service remove           Uninstall the service
    copium service status           Show service health
    copium service logs             Tail service logs
    copium service logs --tail 100  Show last N lines of logs

Design notes:
* This is the "power user" surface for §4b.  Most developers will have
  the proxy auto-installed as a service by `copium init` (§3a) —
  these commands let them manage it explicitly.
* Built on top of copium.install.supervisors which already handles all
  platform differences (systemd / launchd / sc.exe / schtasks).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click

from copium.install.health import probe_ready
from copium.install.models import (
    ConfigScope,
    InstallPreset,
    ProviderSelectionMode,
    RuntimeKind,
    SupervisorKind,
)
from copium.install.paths import log_path
from copium.install.planner import build_manifest
from copium.install.providers import apply_mutations
from copium.install.runtime import runtime_status, wait_ready
from copium.install.state import load_manifest, save_manifest
from copium.install.supervisors import (
    install_supervisor,
    remove_supervisor,
    start_supervisor,
    stop_supervisor,
)

from .main import main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_PROFILE = "default"
_DEFAULT_PORT = 8787


def _ensure_service_manifest(
    port: int = _DEFAULT_PORT,
    scope: str = ConfigScope.USER.value,
    backend: str = "anthropic",
) -> "copium.install.models.DeploymentManifest":  # noqa: F821
    """Load or create a service-capable manifest."""
    existing = load_manifest(_DEFAULT_PROFILE)
    if existing is not None and existing.supervisor_kind == SupervisorKind.SERVICE.value:
        return existing

    manifest = build_manifest(
        profile=_DEFAULT_PROFILE,
        preset=InstallPreset.PERSISTENT_SERVICE.value,
        runtime_kind=RuntimeKind.PYTHON.value,
        scope=scope,
        provider_mode=ProviderSelectionMode.AUTO.value,
        targets=[],
        port=port,
        backend=backend,
        anyllm_provider=None,
        region=None,
        proxy_mode="token",
        memory_enabled=False,
        telemetry_enabled=True,
        image="ghcr.io/iKislay/copium:latest",
    )
    save_manifest(manifest)
    return manifest


# ---------------------------------------------------------------------------
# copium service  (group)
# ---------------------------------------------------------------------------


@main.group("service")
def service() -> None:
    """Manage Copium as a system service (auto-start on login).

    \b
    Commands:
        install     Install & enable autostart service
        remove      Uninstall the service
        status      Show service health
        logs        Tail service logs
    """


# ---------------------------------------------------------------------------
# copium service install
# ---------------------------------------------------------------------------


@service.command("install")
@click.option(
    "--port",
    "-p",
    default=_DEFAULT_PORT,
    type=int,
    show_default=True,
    help="Port for the persistent service.",
)
@click.option(
    "--scope",
    type=click.Choice(["user", "system"]),
    default="user",
    show_default=True,
    help=(
        "user: install as a user-level service (no sudo required, starts on login). "
        "system: install as a system-wide service (requires sudo, starts on boot)."
    ),
)
@click.option(
    "--backend",
    default="anthropic",
    show_default=True,
    help="API backend for the service.",
)
def service_install(port: int, scope: str, backend: str) -> None:
    """Install Copium as a system service (auto-start on login).

    \b
    On Linux:  installs a systemd user unit
               (~/.config/systemd/user/copium.service)
    On macOS:  installs a LaunchAgent plist
               (~/Library/LaunchAgents/com.copium.default.plist)
    On Windows: creates a Windows Service or Task Scheduler entry

    \b
    Examples:
        copium service install            Install user-level service
        copium service install --scope system  System-wide (requires sudo)
    """
    click.echo()
    click.secho("  Installing Copium system service…", bold=True)

    manifest = _ensure_service_manifest(port=port, scope=scope, backend=backend)

    # Re-apply supervisor with updated scope/port
    try:
        manifest.mutations = apply_mutations(manifest)
        manifest.artifacts = install_supervisor(manifest)
        save_manifest(manifest)
    except Exception as exc:
        click.secho(f"  ✗  Service installation failed: {exc}", fg="red", err=True)
        raise SystemExit(1) from None

    # Start it immediately
    try:
        start_supervisor(manifest)
    except Exception as exc:
        click.secho(
            f"  ⚠  Service installed but could not start immediately: {exc}", fg="yellow"
        )

    # Platform-specific success message
    platform = sys.platform
    click.echo()
    click.secho("  ✓  Copium service installed!", fg="green", bold=True)
    click.echo()
    if platform.startswith("linux"):
        scope_flag = "" if scope == "system" else " --user"
        svc_name = manifest.service_name
        click.secho(f"  Service:  systemctl{scope_flag} status {svc_name}", dim=True)
        click.secho(f"  Logs:     journalctl{scope_flag} -u {svc_name} -f", dim=True)
    elif platform == "darwin":
        plist_label = f"com.copium.{_DEFAULT_PROFILE}"
        click.secho(f"  Label:    {plist_label}", dim=True)
        click.secho("  Logs:     copium service logs", dim=True)
    else:
        click.secho(f"  Service name: {manifest.service_name}", dim=True)

    click.echo()
    click.secho("  The proxy will now auto-start on every login.", fg="green")
    click.secho("  Use `copium service status` to check health.", dim=True)
    click.secho("  Use `copium service remove` to uninstall.", dim=True)
    click.echo()


# ---------------------------------------------------------------------------
# copium service remove
# ---------------------------------------------------------------------------


@service.command("remove")
@click.option(
    "-f",
    "--force",
    is_flag=True,
    help="Skip confirmation prompt.",
)
def service_remove(force: bool) -> None:
    """Uninstall the Copium system service.

    Stops the service, removes the unit/plist/task, and clears the
    auto-start configuration. Your proxy data is kept intact.

    \b
    Examples:
        copium service remove           Interactive removal
        copium service remove --force   Skip confirmation
    """
    manifest = load_manifest(_DEFAULT_PROFILE)
    if manifest is None or manifest.supervisor_kind == SupervisorKind.NONE.value:
        click.secho("  ○ No system service is installed.", fg="yellow")
        return

    if not force:
        click.confirm("  Remove the Copium system service?", abort=True)

    click.echo()
    click.secho("  Removing Copium system service…", bold=True)

    try:
        stop_supervisor(manifest)
        click.secho("  ✓  Service stopped.", fg="green")
    except Exception:
        pass  # may already be stopped

    try:
        remove_supervisor(manifest)
        click.secho("  ✓  Service removed.", fg="green")
    except Exception as exc:
        click.secho(f"  ✗  Error removing service: {exc}", fg="red", err=True)
        raise SystemExit(1) from None

    click.echo()
    click.secho("  ✓  Copium service uninstalled.", fg="green", bold=True)
    click.secho("  Your proxy data is still in ~/.copium/", dim=True)
    click.echo()
    click.secho("  Reinstall at any time: copium service install", dim=True)
    click.secho("  Or use: copium start   (manual daemon, no autostart)", dim=True)
    click.echo()


# ---------------------------------------------------------------------------
# copium service status
# ---------------------------------------------------------------------------


@service.command("status")
def service_status() -> None:
    """Show the status of the Copium system service.

    \b
    Examples:
        copium service status
    """
    manifest = load_manifest(_DEFAULT_PROFILE)
    click.echo()

    if manifest is None:
        click.secho("  ○ No Copium deployment profile found.", fg="yellow")
        click.secho("     Install the service: copium service install", dim=True)
        click.echo()
        return

    rs = runtime_status(manifest)
    healthy = probe_ready(manifest.health_url)

    # Supervisor kind label
    sv = manifest.supervisor_kind
    if sv == SupervisorKind.SERVICE.value:
        sv_label = "systemd service" if sys.platform.startswith("linux") else "launchd agent"
    elif sv == SupervisorKind.TASK.value:
        sv_label = "cron / task scheduler"
    else:
        sv_label = "none (manual daemon)"

    status_color = "green" if rs == "running" else "red"
    health_color = "green" if healthy else "red"

    click.secho(f"  Profile:      {manifest.profile}")
    click.secho(f"  Supervisor:   {sv_label}")
    click.secho(f"  Port:         {manifest.port}")
    click.secho(f"  Backend:      {manifest.backend}")
    click.secho(f"  Runtime:      {manifest.runtime_kind}")
    click.secho(f"  Status:       ", nl=False)
    click.secho(rs, fg=status_color, bold=True)
    click.secho(f"  Healthy:      ", nl=False)
    click.secho("yes" if healthy else "no", fg=health_color, bold=True)
    click.secho(f"  Health URL:   {manifest.health_url}")

    click.echo()
    if rs != "running":
        click.secho("  ⚠  Service is not running.", fg="yellow")
        click.secho("     Start it: copium service install  (to reinstall + start)", dim=True)
        click.secho("     Or:       copium start            (manual daemon)", dim=True)
    click.echo()


# ---------------------------------------------------------------------------
# copium service logs
# ---------------------------------------------------------------------------


@service.command("logs")
@click.option(
    "--tail",
    "-n",
    default=50,
    type=int,
    show_default=True,
    help="Number of lines to show (0 = follow continuously).",
)
@click.option(
    "--follow",
    "-f",
    is_flag=True,
    help="Follow the log output (like `tail -f`).",
)
def service_logs(tail: int, follow: bool) -> None:
    """Tail the Copium service logs.

    \b
    Examples:
        copium service logs               Last 50 lines
        copium service logs --tail 100    Last 100 lines
        copium service logs --follow      Tail continuously
        copium service logs -f            Tail continuously (shorthand)
    """
    # Platform-native log commands are preferred for systemd/launchd
    manifest = load_manifest(_DEFAULT_PROFILE)

    if sys.platform.startswith("linux") and manifest and manifest.supervisor_kind == SupervisorKind.SERVICE.value:
        scope = manifest.scope
        flags = [] if scope == "system" else ["--user"]
        cmd = ["journalctl", *flags, "-u", manifest.service_name]
        if follow:
            cmd.extend(["-f"])
        else:
            cmd.extend(["-n", str(tail)])
        try:
            subprocess.run(cmd, check=False)
            return
        except FileNotFoundError:
            pass  # journalctl not available — fall through to file-based

    # Fallback: read the runner log file
    log_file = log_path(_DEFAULT_PROFILE)
    if not log_file.exists():
        # Try the global copium proxy log
        from copium import paths as _paths

        log_file = _paths.proxy_log_path()

    if not log_file.exists():
        click.secho("  No log file found yet.", fg="yellow")
        click.secho(f"  Expected: {log_file}", dim=True)
        click.secho("  The proxy may not have started yet.", dim=True)
        return

    if follow:
        try:
            subprocess.run(["tail", "-f", str(log_file)], check=False)
        except KeyboardInterrupt:
            pass
    else:
        try:
            subprocess.run(["tail", "-n", str(tail), str(log_file)], check=False)
        except FileNotFoundError:
            # Windows — read directly
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in lines[-tail:]:
                click.echo(line)
