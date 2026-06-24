"""Command to list detected AI agents and their wrap status."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass

import click

from . import console

# Known agent binaries and their display names
KNOWN_AGENTS: dict[str, str] = {
    "claude": "Claude Code",
    "cursor": "Cursor",
    "aider": "Aider",
    "opencode": "OpenCode",
    "codex": "Codex CLI",
    "copilot": "GitHub Copilot CLI",
    "cline": "Cline",
    "continue": "Continue",
    "vibe": "Vibe",
    "openclaw": "OpenClaw",
}


@dataclass
class AgentInfo:
    """Information about a detected agent."""

    name: str
    display_name: str
    binary: str | None
    is_wrapped: bool  # Is ANTHROPIC_BASE_URL/OPENAI_API_BASE set for Copium?


def _detect_agents() -> list[AgentInfo]:
    """Detect all known agents on PATH and their wrap status."""
    agents = []
    anthropic_set = os.environ.get("ANTHROPIC_BASE_URL", "")
    openai_set = os.environ.get("OPENAI_API_BASE", "")

    for binary, display_name in KNOWN_AGENTS.items():
        path = shutil.which(binary)
        is_wrapped = bool(
            anthropic_set and "localhost" in anthropic_set
        ) or bool(openai_set and "localhost" in openai_set)
        agents.append(
            AgentInfo(
                name=binary,
                display_name=display_name,
                binary=path,
                is_wrapped=is_wrapped,
            )
        )

    return agents


@click.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option("--installed", is_flag=True, help="Show only installed agents.")
def agents(as_json: bool, installed: bool) -> None:
    """List all detected AI agents and their wrap status.

    Shows which agents are installed on your system and whether they are
    configured to route through the Copium proxy.

    \b
    Examples:
        copium agents              Show all known agents
        copium agents --installed  Show only installed agents
        copium agents --json       Machine-readable output
    """
    agent_list = _detect_agents()

    if installed:
        agent_list = [a for a in agent_list if a.binary is not None]

    if as_json:
        data = [
            {
                "name": a.name,
                "display_name": a.display_name,
                "binary": a.binary,
                "installed": a.binary is not None,
                "is_wrapped": a.is_wrapped,
            }
            for a in agent_list
        ]
        click.echo(json.dumps(data, indent=2))
        return

    from rich.table import Table

    from . import SUCCESS

    table = Table(title="Detected AI Agents")
    table.add_column("Agent", style="bold")
    table.add_column("Status")
    table.add_column("Wrap Status")

    for agent in agent_list:
        if agent.binary:
            status = f"[green]{SUCCESS}[/green] {agent.binary}"
        else:
            status = "[dim]not installed[/dim]"

        if agent.is_wrapped:
            wrap = "[green]wrapped[/green]"
        else:
            wrap = "[dim]not wrapped[/dim]"

        table.add_row(agent.display_name, status, wrap)

    console.print(table)

    # Show hint if no agents are wrapped
    if not any(a.is_wrapped for a in agent_list if a.binary):
        console.print(
            "\n[dim]No agents are currently wrapped. Run "
            "[bold]copium wrap <agent>[/bold] to configure an agent.[/dim]"
        )
