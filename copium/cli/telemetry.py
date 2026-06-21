"""Telemetry management CLI command."""

import os

import click

from .main import main


@main.command()
@click.option("--enable", is_flag=True, help="Enable anonymous telemetry")
@click.option("--disable", is_flag=True, help="Disable anonymous telemetry")
@click.option("--status", is_flag=True, help="Show current telemetry status")
def telemetry(enable: bool, disable: bool, status: bool) -> None:
    """Manage anonymous telemetry settings.

    \b
    Telemetry is OFF by default. Your data stays local.
    Enable to send anonymous aggregate stats (tokens saved, compression ratios)
    to help improve Copium. No prompts, no content, no PII.

    \b
    Examples:
        copium telemetry --status     Show current setting
        copium telemetry --enable     Opt-in to anonymous stats
        copium telemetry --disable    Opt-out (default)
    """
    from copium.telemetry.beacon import is_telemetry_enabled

    if enable and disable:
        raise click.ClickException("Cannot use both --enable and --disable")

    if status or (not enable and not disable):
        # Show current status
        enabled = is_telemetry_enabled()
        if enabled:
            click.echo("Telemetry: ENABLED (anonymous aggregate stats)")
            click.echo("Disable:  copium telemetry --disable")
        else:
            click.echo("Telemetry: DISABLED (your data stays local)")
            click.echo("Enable:   copium telemetry --enable")
        return

    if enable:
        os.environ["COPIUM_TELEMETRY"] = "on"
        # Persist to shell profile
        _update_shell_profile("on")
        click.echo("Telemetry: ENABLED")
        click.echo("Anonymous aggregate stats will be sent to help improve Copium.")
        click.echo("No prompts, no content, no PII.")

    if disable:
        os.environ["COPIUM_TELEMETRY"] = "off"
        _update_shell_profile("off")
        click.echo("Telemetry: DISABLED")
        click.echo("Your data stays local.")


def _update_shell_profile(value: str) -> None:
    """Persist telemetry setting to shell profile."""
    import pathlib

    home = pathlib.Path.home()
    env_line = f"export COPIUM_TELEMETRY={value}"

    # Try common shell profiles
    for profile_name in [".bashrc", ".zshrc", ".profile"]:
        profile_path = home / profile_name
        if profile_path.exists():
            content = profile_path.read_text()
            # Remove existing COPIUM_TELEMETRY line if present
            lines = [line for line in content.splitlines() if "COPIUM_TELEMETRY" not in line]
            lines.append(env_line)
            profile_path.write_text("\n".join(lines) + "\n")
            click.echo(f"Saved to {profile_path}")
            return

    # Fallback: create .copium/telemetry env file
    env_dir = home / ".copium"
    env_dir.mkdir(exist_ok=True)
    env_file = env_dir / "telemetry.env"
    env_file.write_text(env_line + "\n")
    click.echo(f"Saved to {env_file}")
