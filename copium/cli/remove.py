"""Clean uninstall command for Copium.

Plan §3b: `copium remove` removes all traces of Copium from the system,
including shell rc file modifications, global config, data directory, and
any registered services.

Usage:
    copium remove              Interactive removal with confirmation
    copium remove --force      Skip confirmation prompts
    copium remove --help       Show help
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import click

from copium.install.runtime import stop_runtime
from copium.install.state import delete_manifest, list_manifests

from .init import (
    _get_user_shell_rc_files,
    _remove_copium_from_shell_rc_files,
    _remove_global_config,
    _remove_shell_rc_prompt,
    _remove_starship_copium_module,
)
from .main import main

logger = logging.getLogger(__name__)


def _remove_copium_directory(workspace_dir: Path) -> bool:
    """Remove the Copium workspace directory."""
    if not workspace_dir.exists():
        return False
    shutil.rmtree(workspace_dir, ignore_errors=True)
    return True


def _remove_deployment_profiles() -> list[str]:
    """Stop and remove all deployment profiles."""
    removed: list[str] = []
    for manifest in list_manifests():
        try:
            stop_runtime(manifest)
        except Exception:
            logger.debug("failed to stop profile %s", manifest.profile)
        delete_manifest(manifest.profile)
        removed.append(manifest.profile)
    return removed


@main.command()
@click.option("-f", "--force", is_flag=True, help="Skip confirmation prompts.")
@click.option("-v", "--verbose", is_flag=True, help="Show detailed removal steps.")
def remove(force: bool, verbose: bool) -> None:
    """Fully remove Copium from your system.

    Reverses everything `copium init` configured: cleans shell rc files,
    removes the global config, deletes the Copium data directory, and
    unregisters any system services.

    \b
    Examples:
        copium remove              Interactive removal with confirmation
        copium remove --force      Skip all confirmation prompts
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    click.echo()
    click.secho("  Copium Removal", bold=True)
    click.echo("  " + "=" * 50)
    click.echo()

    steps: list[tuple[str, str]] = []

    # 1a. Clean shell rc files (env vars)
    cleaned = _remove_copium_from_shell_rc_files()
    if cleaned:
        for rc in cleaned:
            click.secho(f"  ✓ Cleaned env vars from {rc}", fg="green")
            steps.append(("shell-rc", str(rc)))
    else:
        click.echo("  - No shell rc files needed cleaning")

    # 1b. Clean shell prompt integration (§9a)
    prompt_cleaned: list[str] = []
    for rc_file in _get_user_shell_rc_files():
        if _remove_shell_rc_prompt(rc_file):
            click.secho(f"  ✓ Cleaned prompt integration from {rc_file}", fg="green")
            prompt_cleaned.append(str(rc_file))
            steps.append(("shell-prompt-rc", str(rc_file)))
    if _remove_starship_copium_module():
        click.secho("  ✓ Removed Copium module from starship.toml", fg="green")
        steps.append(("starship", "removed"))

    # 2. Remove global config
    if _remove_global_config():
        click.secho("  ✓ Removed global config (~/.copium/config.toml)", fg="green")
        steps.append(("global-config", "removed"))

    # 3. Stop and remove deployment profiles
    profiles = _remove_deployment_profiles()
    if profiles:
        for profile in profiles:
            click.secho(f"  ✓ Stopped and removed profile: {profile}", fg="green")
            steps.append(("profile", profile))

    # 4. Remove the Copium data directory
    copium_dir = Path.home() / ".copium"
    if copium_dir.exists():
        if force or click.confirm(
            f"  Remove the Copium data directory ({copium_dir})?", default=True
        ):
            _remove_copium_directory(copium_dir)
            click.secho(f"  ✓ Removed {copium_dir}", fg="green")
            steps.append(("data-dir", str(copium_dir)))
        else:
            click.secho(
                f"  ⚠ Skipped removing {copium_dir}. You can remove it manually:",
                fg="yellow",
            )
            click.secho(f"    rm -rf {copium_dir}", fg="yellow")
    else:
        click.echo("  - No Copium data directory found")

    click.echo()
    click.echo("  " + "=" * 50)

    if steps:
        click.echo()
        click.secho("  ✓ Copium has been fully removed.", fg="green", bold=True)
        click.secho("  Your original agent settings have been restored.", fg="green")
        click.echo()
        click.echo("  To reinstall, run:")
        click.secho("    copium init", fg="yellow")
    else:
        click.echo()
        click.echo("  No Copium configuration found. Nothing to remove.")
