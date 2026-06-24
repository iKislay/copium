"""Main CLI entry point for Copium."""

import platform
import sys

import click

CLI_CONTEXT_SETTINGS = {"help_option_names": ["--help", "-?"]}


def get_version() -> str:
    """Get the current version."""
    try:
        from copium._version import __version__

        return __version__
    except ImportError:
        return "unknown"


@click.group(context_settings=CLI_CONTEXT_SETTINGS)
@click.version_option(get_version(), "--version", "-v", prog_name="copium")
@click.pass_context
def main(ctx: click.Context) -> None:
    """Copium - The Context Optimization Layer for LLM Applications.

    Manage memories, run the optimization proxy, and analyze metrics.

    \b
    Examples:
        copium proxy              Start the optimization proxy
        copium memory list        List stored memories
        copium memory stats       Show memory statistics
        copium update             Update Copium to the latest release
    """
    ctx.ensure_object(dict)

    # Fire a rate-limited, opt-out background check for newer releases so other
    # surfaces (e.g. the proxy banner) can show an "update available" notice.
    # Never blocks, never raises; skipped for `update` (it checks explicitly).
    if ctx.invoked_subcommand != "update":
        try:
            from copium.update_check import maybe_check_async

            maybe_check_async()
        except Exception:  # noqa: BLE001 — update check must never break the CLI
            pass


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def version(as_json: bool) -> None:
    """Show Copium version, platform, and install info."""
    ver = get_version()
    python_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    platform_info = f"{platform.system().lower()}-{platform.machine()}"

    # Detect install method
    install_method = "unknown"
    try:
        import importlib.metadata

        dist = importlib.metadata.distribution("copium-ai")
        if dist.read_text("INSTALLER") == "pipx":
            install_method = "pipx"
        elif dist.read_text("INSTALLER") == "uv":
            install_method = "uv"
        else:
            install_method = "pip"
    except Exception:
        pass

    if as_json:
        import json

        click.echo(
            json.dumps(
                {
                    "version": ver,
                    "python": python_ver,
                    "platform": platform_info,
                    "install_method": install_method,
                }
            )
        )
    else:
        from rich.panel import Panel

        from . import console

        console.print(
            Panel(
                f"[bold]copium[/bold] {ver}\n"
                f"Python {python_ver} on {platform_info}\n"
                f"Install method: {install_method}",
                title="Version Info",
            )
        )


# Import subcommands - these register themselves with the main group
def _register_commands() -> None:
    """Register all subcommand groups."""
    from . import (
        agent_savings,  # noqa: F401
        agents,  # noqa: F401
        audit,  # noqa: F401
        benchmark_cmd,  # noqa: F401
        capture,  # noqa: F401
        config_cmd,  # noqa: F401 — config show/set/reset/path (§5)
        copilot_auth,  # noqa: F401
        daemon,  # noqa: F401 — start / stop / restart / status (§4a)
        dashboard_tui,  # noqa: F401
        doctor,  # noqa: F401
        evals,  # noqa: F401
        hooks_compress,  # noqa: F401
        init,  # noqa: F401
        install,  # noqa: F401
        learn,  # noqa: F401
        mcp,  # noqa: F401
        output_savings,  # noqa: F401
        perf,  # noqa: F401
        preset_cmd,  # noqa: F401
        prioritize,  # noqa: F401
        proxy,  # noqa: F401
        quickstart,  # noqa: F401
        recipe,  # noqa: F401
        remove,  # noqa: F401
        report_cmd,  # noqa: F401
        service_cmd,  # noqa: F401 — service install/remove/status/logs (§4b)
        stats,  # noqa: F401
        tools,  # noqa: F401
        update,  # noqa: F401
        wrap,  # noqa: F401
    )

    # Memory CLI requires numpy/hnswlib — optional
    try:
        from . import memory  # noqa: F401
    except ImportError:
        pass


_register_commands()


def _apply_help_aliases(command: click.Command) -> None:
    """Ensure `-?` works everywhere in the Click command tree."""
    context_settings = dict(command.context_settings or {})
    help_option_names = list(context_settings.get("help_option_names", []))
    if "--help" not in help_option_names:
        help_option_names.append("--help")
    if "-?" not in help_option_names:
        help_option_names.append("-?")
    context_settings["help_option_names"] = help_option_names
    command.context_settings = context_settings

    if isinstance(command, click.Group):
        for child in command.commands.values():
            _apply_help_aliases(child)


_apply_help_aliases(main)

if __name__ == "__main__":
    main()
