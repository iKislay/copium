"""``copium config`` command group — inspect and edit Copium configuration.

Plan §5 — Global vs. Project Config.

Mirrors the mental model of ``git config`` / ``npm config``:
    copium config                      Show resolved config (global + project)
    copium config --global             Show only global config
    copium config set <key> <value>    Set a project-level value
    copium config set --global <k> <v> Set a global value
    copium config reset                Reset config to defaults
    copium config path                 Print config file path(s)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from .main import main

# ---------------------------------------------------------------------------
# Valid keys for --help display
# ---------------------------------------------------------------------------

_VALID_KEYS = [
    ("proxy.port", "Proxy listen port (default: 8787)"),
    ("proxy.host", "Proxy bind host (default: 127.0.0.1)"),
    ("proxy.backend", "API backend: anthropic, bedrock, openrouter, litellm-*"),
    ("proxy.mode", "Optimization mode: token or cache"),
    ("compression.preset", "Named preset: standard, aggressive, minimal, local-llm, lossless"),
    ("compression.quality_gate", "Auto-revert on token inflation (true/false)"),
    ("compression.smart_crusher.max_items_after_crush", "Max items after SmartCrusher (int)"),
    ("compression.smart_crusher.min_tokens_to_crush", "Min tokens to trigger SmartCrusher (int)"),
    ("compression.session_dedup.enabled", "Enable session deduplication (true/false)"),
    ("compression.session_dedup.minhash_threshold", "Near-duplicate threshold 0-1 (float)"),
    ("compression.error_compressor.enabled", "Enable error compression (true/false)"),
    ("compression.error_compressor.max_stack_frames", "Stack frames kept in errors (int)"),
    ("compression.output_compressor.enabled", "Enable output compression (true/false)"),
    ("compression.context_budget.enabled", "Enable context budget management (true/false)"),
    ("dashboard.port", "Dashboard web UI port (default: 8787)"),
    ("dashboard.open_on_start", "Auto-open dashboard on proxy start (true/false)"),
    ("telemetry.enabled", "Anonymous telemetry opt-in (true/false)"),
]


# ---------------------------------------------------------------------------
# copium config
# ---------------------------------------------------------------------------


@main.group("config", invoke_without_command=True)
@click.option("--global", "global_scope", is_flag=True, help="Show only global config.")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output as JSON (machine-readable).",
)
@click.pass_context
def config_group(ctx: click.Context, global_scope: bool, as_json: bool) -> None:
    """Show resolved configuration (global + project merged).

    \b
    Examples:
        copium config                Show full resolved config
        copium config --global       Show only global config (~/.copium/config.toml)
        copium config --json         Output as JSON

    \b
    Config hierarchy (last wins):
        1. ~/.copium/config.toml   Global defaults
        2. <project>/copium.json   Project overrides

    \b
    Use `copium config set <key> <value>` to edit configuration.
    Use `copium config path` to show config file locations.
    """
    if ctx.invoked_subcommand is not None:
        return

    from copium.config_loader import show_merged_flat

    flat = show_merged_flat(global_only=global_scope)

    if as_json:
        click.echo(json.dumps(flat, indent=2))
        return

    if not flat:
        scope = "global" if global_scope else "merged"
        click.secho(f"  No {scope} config found.", fg="yellow")
        click.echo()
        click.echo("  Create one with: copium init")
        click.echo("  Or set values:   copium config set <key> <value>")
        return

    # Group by section
    sections: dict[str, list[tuple[str, str]]] = {}
    for key in sorted(flat):
        section = key.split(".")[0]
        sections.setdefault(section, []).append((key, _format_value(flat[key])))

    click.echo()
    click.secho("  Copium Configuration", bold=True)
    if global_scope:
        click.secho("  (global only — ~/.copium/config.toml)", dim=True)
    else:
        click.secho("  (merged: global + project)", dim=True)
    click.echo()

    for section_name, items in sections.items():
        click.secho(f"  [{section_name}]", fg="cyan")
        for key, val in items:
            short_key = key[len(section_name) + 1 :]  # strip "section."
            click.echo(f"    {short_key:<35s} {val}")
        click.echo()

    click.secho("  Edit: copium config set <key> <value>", dim=True)
    click.secho("  Docs: https://copium-docs.vercel.app/docs/config", dim=True)
    click.echo()


def _format_value(v: object) -> str:
    """Format a config value for display."""
    if isinstance(v, bool):
        return click.style("true" if v else "false", fg="green")
    if isinstance(v, (int, float)):
        return click.style(str(v), fg="green")
    if isinstance(v, str):
        return click.style(f'"{v}"', fg="green")
    return click.style(str(v), fg="green")


# ---------------------------------------------------------------------------
# copium config set
# ---------------------------------------------------------------------------


@config_group.command("set")
@click.argument("key")
@click.argument("value")
@click.option("--global", "global_scope", is_flag=True, help="Set in global config.")
def config_set(key: str, value: str, global_scope: bool) -> None:
    """Set a configuration value.

    \b
    Examples:
        copium config set proxy.port 9090
        copium config set compression.preset aggressive
        copium config set --global proxy.port 8082
        copium config set telemetry.enabled true

    \b
    Run `copium config` to see available keys.
    """
    from copium.config_loader import set_config_value

    config_path = set_config_value(key, value, global_scope=global_scope)
    scope = "global" if global_scope else "project"
    click.secho(f"  ✓ Set {key} = {value}", fg="green")
    click.secho(f"    ({scope} config: {config_path})", dim=True)
    click.echo()


# ---------------------------------------------------------------------------
# copium config reset
# ---------------------------------------------------------------------------


@config_group.command("reset")
@click.option("--global", "global_scope", is_flag=True, help="Reset global config.")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
def config_reset(global_scope: bool, yes: bool) -> None:
    """Reset configuration to defaults (removes config file).

    \b
    Examples:
        copium config reset            Reset project config
        copium config reset --global   Reset global config
        copium config reset -y         Skip confirmation
    """
    from copium.config_loader import find_project_config_path, reset_config

    scope = "global" if global_scope else "project"
    config_path = (
        Path.home() / ".copium" / "config.toml"
        if global_scope
        else (find_project_config_path() or (Path.cwd() / "copium.json"))
    )

    if not config_path.exists():
        click.secho(f"  No {scope} config to reset.", fg="yellow")
        return

    if not yes:
        click.echo(f"  This will remove {config_path}")
        if not click.confirm("  Continue?"):
            click.echo("  Aborted.")
            return

    reset_config(global_scope=global_scope)
    click.secho(f"  ✓ {scope.capitalize()} config removed: {config_path}", fg="green")
    click.echo()


# ---------------------------------------------------------------------------
# copium config path
# ---------------------------------------------------------------------------


@config_group.command("path")
def config_path() -> None:
    """Print config file paths and whether they exist.

    \b
    Examples:
        copium config path
    """
    from copium.config_loader import _GLOBAL_CONFIG_PATH, find_project_config_path

    global_path = _GLOBAL_CONFIG_PATH
    project_path = find_project_config_path()

    click.echo()
    click.secho("  Config file locations:", bold=True)
    click.echo()

    # Global
    if global_path.exists():
        click.secho(f"  ✓ Global:    {global_path}", fg="green")
    else:
        click.secho(f"  ○ Global:    {global_path}", fg="yellow")
        click.secho("    (not created yet — run: copium init)", dim=True)

    # Project
    if project_path:
        click.secho(f"  ✓ Project:   {project_path}", fg="green")
    else:
        cwd = Path.cwd()
        expected = cwd / "copium.json"
        click.secho(f"  ○ Project:   {expected}", fg="yellow")
        click.secho("    (not created yet — run: copium config set <key> <value>)", dim=True)

    click.echo()


# ---------------------------------------------------------------------------
# copium config keys (hidden helper)
# ---------------------------------------------------------------------------


@config_group.command("keys", hidden=True)
def config_keys() -> None:
    """List all valid config keys."""
    click.echo()
    click.secho("  Valid configuration keys:", bold=True)
    click.echo()
    for key, desc in _VALID_KEYS:
        click.echo(f"    {key:<45s} {desc}")
    click.echo()
