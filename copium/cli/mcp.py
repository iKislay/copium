"""MCP (Model Context Protocol) CLI commands for Claude Code integration.

Provides commands to configure and run the Copium MCP server, enabling
Claude Code subscription users to use CCR (Compress-Cache-Retrieve) without
needing API key access.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import click

from .main import main

# Default paths
CLAUDE_CONFIG_DIR = Path.home() / ".claude"
MCP_CONFIG_PATH = CLAUDE_CONFIG_DIR / "mcp.json"
DEFAULT_PROXY_URL = "http://127.0.0.1:8787"


def get_copium_command() -> list[str]:
    """Get the command to run copium MCP server.

    Returns the CLI invocation used by Claude Code config.
    """
    return ["copium", "mcp", "serve"]


def load_mcp_config() -> dict[str, Any]:
    """Load existing MCP config or return empty structure."""
    if MCP_CONFIG_PATH.exists():
        try:
            with open(MCP_CONFIG_PATH) as f:
                result: dict[str, Any] = json.load(f)
                return result
        except (json.JSONDecodeError, OSError):
            return {"mcpServers": {}}
    return {"mcpServers": {}}


def save_mcp_config(config: dict) -> None:
    """Save MCP config, creating directory if needed."""
    CLAUDE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(MCP_CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")  # Trailing newline


@main.group()
def mcp() -> None:
    """MCP server for Claude Code integration.

    \b
    The MCP server exposes copium_retrieve as a tool that Claude Code
    can use to retrieve compressed content. This enables CCR (Compress-
    Cache-Retrieve) for subscription users who don't have API access.

    \b
    Quick Start:
        copium mcp install    # Configure Claude Code
        copium proxy          # Start the proxy (in another terminal)
        ANTHROPIC_BASE_URL=http://127.0.0.1:8787 claude

    \b
    The MCP server provides on-demand tools (compress, retrieve, stats).
    For automatic compression of ALL traffic, also set ANTHROPIC_BASE_URL
    to route through the proxy.

    \b
    How it works:
        1. ANTHROPIC_BASE_URL routes all requests through the proxy
        2. The proxy compresses large tool outputs (file listings, search results)
        3. Claude sees compressed summaries with hash markers
        4. When Claude needs full details, it calls copium_retrieve
        5. The MCP server fetches original content from the proxy

    \b
    Note on tool naming: MCP clients display tools as
    `mcp__<server>__<tool>`. Our server is named "copium" and our
    tools are named copium_retrieve / copium_compress / etc., so
    Claude Code shows them as `mcp__copium__copium_retrieve`. The
    "copium" doubling is normal MCP namespacing — not a bug. The
    proxy's compression markers (and any docs/prompts) reference the
    bare tool name `copium_retrieve`.
    """
    pass


@mcp.command("install")
@click.option(
    "--proxy-url",
    default=DEFAULT_PROXY_URL,
    help=f"Copium proxy URL (default: {DEFAULT_PROXY_URL})",
)
@click.option(
    "--agent",
    "agents",
    multiple=True,
    help="Restrict installation to specific agents (default: every detected agent).",
)
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite existing copium config in case of mismatch.",
)
def mcp_install(proxy_url: str, agents: tuple[str, ...], force: bool) -> None:
    """Install the Copium MCP server into every detected coding agent.

    \b
    By default this installs into every agent that has a registrar and is
    detected on this system (Claude Code today; Cursor / Codex / Continue /
    others added in subsequent releases). Pass ``--agent NAME`` one or more
    times to restrict the installation.

    \b
    Examples:
        copium mcp install                            # every detected agent
        copium mcp install --agent claude             # Claude Code only
        copium mcp install --proxy-url http://localhost:9000
    """
    try:
        import mcp  # noqa: F401
    except ImportError:
        click.echo("Error: MCP SDK not installed.", err=True)
        click.echo("Install with: pip install 'copium-ai[mcp]'", err=True)
        raise SystemExit(1) from None

    from copium.mcp_registry import any_succeeded, format_results, install_everywhere

    results = install_everywhere(
        proxy_url=proxy_url,
        agents=list(agents) if agents else None,
        force=force,
    )

    if not results:
        click.echo("No agents matched the requested filter.")
        raise SystemExit(1)

    click.echo("Installing Copium MCP server...")
    for line in format_results(
        results,
        verbose=True,
        overwrite_hint=f"copium mcp install --proxy-url {proxy_url} --force",
    ):
        click.echo(line)

    if not any_succeeded(results):
        raise SystemExit(1)

    click.echo(
        f"\nNext steps:\n"
        f"  1. Start the Copium proxy (if not running): copium proxy\n"
        f"  2. Start your agent (e.g.) ANTHROPIC_BASE_URL={proxy_url} claude\n"
        f"  3. Restart any agent that was already running so it picks up the new MCP server.\n"
    )


@mcp.command("uninstall")
def mcp_uninstall() -> None:
    """Remove Copium MCP server from Claude Code config.

    \b
    Removes copium from both the claude CLI registry (Claude Code CLI >=2.x)
    and ~/.claude/mcp.json if present. Other MCP servers are preserved.
    """
    removed = False

    # Remove from claude CLI registry (Claude Code CLI >=2.x)
    claude_cli = shutil.which("claude")
    if claude_cli:
        check = subprocess.run(
            [claude_cli, "mcp", "get", "copium"],
            capture_output=True,
        )
        if check.returncode == 0:
            rm = subprocess.run(
                [claude_cli, "mcp", "remove", "copium", "-s", "user"],
                capture_output=True,
                text=True,
            )
            if rm.returncode == 0:
                click.echo("✓ Copium MCP server removed (via claude mcp remove)")
                removed = True
            else:
                click.echo(
                    f"Warning: 'claude mcp remove' failed ({rm.stderr.strip()}).",
                    err=True,
                )

    # Also remove codebase-memory-mcp if registered (installed by --code-graph)
    if claude_cli:
        cbm_check = subprocess.run(
            [claude_cli, "mcp", "get", "codebase-memory-mcp"],
            capture_output=True,
        )
        if cbm_check.returncode == 0:
            cbm_rm = subprocess.run(
                [claude_cli, "mcp", "remove", "codebase-memory-mcp", "-s", "user"],
                capture_output=True,
                text=True,
            )
            if cbm_rm.returncode == 0:
                click.echo("✓ codebase-memory-mcp MCP server removed")
                removed = True

    # Also remove from mcp.json fallback config if present
    if MCP_CONFIG_PATH.exists():
        config = load_mcp_config()
        changed = False
        for server_name in ("copium", "codebase-memory-mcp"):
            if server_name in config.get("mcpServers", {}):
                del config["mcpServers"][server_name]
                changed = True
        if changed:
            save_mcp_config(config)
            click.echo(f"✓ MCP servers removed from {MCP_CONFIG_PATH}")
            removed = True

    if not removed:
        if MCP_CONFIG_PATH.exists():
            click.echo("Copium MCP is not configured. Nothing to uninstall.")
        else:
            click.echo("No MCP config found. Nothing to uninstall.")


@mcp.command("status")
def mcp_status() -> None:
    """Check Copium MCP configuration status.

    \b
    Shows whether copium is configured in Claude Code and if
    the proxy is reachable.
    """
    click.echo("Copium MCP Status")
    click.echo("=" * 40)

    # Check MCP SDK
    try:
        import mcp  # noqa: F401

        click.echo("MCP SDK:        ✓ Installed")
    except ImportError:
        click.echo("MCP SDK:        ✗ Not installed")
        click.echo("                pip install 'copium-ai[mcp]'")

    # Check config
    if MCP_CONFIG_PATH.exists():
        config = load_mcp_config()
        if "copium" in config.get("mcpServers", {}):
            server_config = config["mcpServers"]["copium"]
            click.echo("Claude Config:  ✓ Configured")
            click.echo(f"                {MCP_CONFIG_PATH}")

            # Show proxy URL
            env = server_config.get("env", {})
            proxy_url = env.get("COPIUM_PROXY_URL", DEFAULT_PROXY_URL)
            click.echo(f"Proxy URL:      {proxy_url}")
        else:
            click.echo("Claude Config:  ✗ Not configured")
            click.echo("                Run: copium mcp install")
    else:
        click.echo("Claude Config:  ✗ No config file")
        click.echo("                Run: copium mcp install")

    # Check proxy connectivity
    try:
        import httpx

        config = load_mcp_config()
        env = config.get("mcpServers", {}).get("copium", {}).get("env", {})
        proxy_url = env.get("COPIUM_PROXY_URL", DEFAULT_PROXY_URL)

        try:
            response = httpx.get(f"{proxy_url}/health", timeout=2.0)
            if response.status_code == 200:
                click.echo(f"Proxy Status:   ✓ Running at {proxy_url}")
            else:
                click.echo(f"Proxy Status:   ✗ Unhealthy (status {response.status_code})")
        except httpx.ConnectError:
            click.echo("Proxy Status:   ✗ Not running")
            click.echo("                Run: copium proxy")
        except httpx.TimeoutException:
            click.echo("Proxy Status:   ✗ Timeout")
    except ImportError:
        click.echo("Proxy Status:   ? (httpx not installed)")


@mcp.command("serve")
@click.option(
    "--proxy-url",
    default=None,
    envvar="COPIUM_PROXY_URL",
    help=f"Copium proxy URL (default: {DEFAULT_PROXY_URL})",
)
@click.option(
    "--direct",
    is_flag=True,
    help="(Deprecated, ignored) Direct CompressionStore access is no longer supported",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug logging",
)
def mcp_serve(proxy_url: str | None, direct: bool, debug: bool) -> None:
    """Start the MCP server (called by Claude Code).

    \b
    This command is typically invoked by Claude Code via the MCP config,
    not run directly. It starts the MCP server with stdio transport.

    \b
    For manual testing:
        copium mcp serve --debug
    """
    import asyncio
    import logging

    # Check for MCP SDK
    try:
        from copium.ccr.mcp_server import create_ccr_mcp_server
    except ImportError as e:
        click.echo(f"Error: MCP dependencies not installed: {e}", err=True)
        click.echo("Install with: pip install 'copium-ai[mcp]'", err=True)
        raise SystemExit(1) from None

    if debug:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
    else:
        # Minimal logging for MCP (stdout is used for protocol)
        logging.basicConfig(
            level=logging.WARNING,
            format="%(levelname)s: %(message)s",
        )

    # Use default if not specified
    effective_proxy_url = proxy_url or DEFAULT_PROXY_URL

    if direct:
        click.echo(
            "Warning: --direct is deprecated and ignored; MCP retrieval uses the proxy URL.",
            err=True,
        )

    server = create_ccr_mcp_server(proxy_url=effective_proxy_url)

    async def run() -> None:
        try:
            await server.run_stdio()
        finally:
            await server.cleanup()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass  # Clean exit on Ctrl+C


# ---------------------------------------------------------------------------
# MCP Proxy subcommands
# ---------------------------------------------------------------------------


@mcp.group("proxy")
def mcp_proxy() -> None:
    """MCP compression proxy — transparent compression layer.

    \b
    The proxy sits between your AI coding tool and upstream MCP servers,
    compressing tool descriptions, schemas, and responses transparently.

    \b
    Quick Start:
        copium mcp proxy install                  # Configure all detected agents
        copium mcp proxy install --agent cursor   # Configure specific agent
        copium mcp proxy serve                    # Start the proxy server
        copium mcp proxy status                   # Show compression stats
        copium mcp proxy detect                   # Detect available agents
    """
    pass


@mcp_proxy.command("serve")
@click.option(
    "--config",
    "config_path",
    default=None,
    envvar="COPIUM_PROXY_CONFIG",
    help="Path to proxy config file (default: ~/.copium/mcp-proxy.json)",
)
@click.option("--debug", is_flag=True, help="Enable debug logging")
def proxy_serve(config_path: str | None, debug: bool) -> None:
    """Start the MCP compression proxy server.

    \b
    Launches upstream servers, discovers tools, and serves compressed
    MCP protocol to the agent via stdio transport.

    \b
    Example:
        copium mcp proxy serve --config ~/.copium/mcp-proxy.json
    """
    import asyncio
    import logging

    if debug:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
    else:
        logging.basicConfig(
            level=logging.WARNING,
            format="%(levelname)s: %(message)s",
        )

    from copium.mcp_proxy.config import ProxyConfig
    from copium.mcp_proxy.proxy import CopiumMCPProxy

    if config_path:
        config = ProxyConfig.from_file(config_path)
    else:
        config = ProxyConfig.from_env()

    config.debug = debug
    proxy = CopiumMCPProxy(config)

    async def run() -> None:
        try:
            await proxy.serve()
        finally:
            await proxy.shutdown()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


@mcp_proxy.command("install")
@click.option(
    "--agent",
    "agent_name",
    default=None,
    help="Specific agent to install for (default: all detected).",
)
@click.option(
    "--config",
    "config_path",
    default=None,
    help="Path to proxy config file.",
)
def proxy_install(agent_name: str | None, config_path: str | None) -> None:
    """Install the MCP proxy into detected AI coding tools.

    \b
    Detects installed agents (Claude Code, Cursor, Codex, etc.) and
    configures them to use the Copium proxy. Existing MCP servers are
    migrated to upstream configuration.

    \b
    Examples:
        copium mcp proxy install                    # all agents
        copium mcp proxy install --agent claude-code
        copium mcp proxy install --agent cursor
    """
    from copium.mcp_proxy.installers import install_proxy

    results = install_proxy(agent_name=agent_name, config_path=config_path)

    if not results:
        click.echo("No agents detected. Install Claude Code, Cursor, or Codex first.")
        raise SystemExit(1)

    for result in results:
        icon = "✓" if result.success else "✗"
        click.echo(f"  {icon} {result.agent}: {result.message}")
        if result.backup_path:
            click.echo(f"    Backup: {result.backup_path}")

    if any(r.success for r in results):
        click.echo(
            "\nNext: Start the proxy with 'copium mcp proxy serve' "
            "then restart your agent."
        )


@mcp_proxy.command("uninstall")
@click.option(
    "--agent",
    "agent_name",
    default=None,
    help="Specific agent to uninstall from (default: all).",
)
def proxy_uninstall(agent_name: str | None) -> None:
    """Remove the MCP proxy from agent configs."""
    from copium.mcp_proxy.installers import uninstall_proxy

    results = uninstall_proxy(agent_name=agent_name)

    for result in results:
        icon = "✓" if result.success else "✗"
        click.echo(f"  {icon} {result.agent}: {result.message}")


@mcp_proxy.command("detect")
def proxy_detect() -> None:
    """Detect installed MCP-capable AI coding tools.

    \b
    Scans for known agent config files and reports which are available
    for proxy installation.
    """
    from copium.mcp_proxy.installers import detect_agents

    agents = detect_agents()

    if not agents:
        click.echo("No MCP-capable agents detected.")
        click.echo("Supported: Claude Code, Claude Desktop, Cursor, Codex, Continue, Zed")
        return

    click.echo("Detected MCP-capable agents:")
    for agent in agents:
        proxy_status = " (proxy installed)" if agent.installed else ""
        server_count = len(agent.servers)
        click.echo(
            f"  • {agent.name}: {server_count} servers "
            f"({agent.config_path}){proxy_status}"
        )

    click.echo(f"\nRun 'copium mcp proxy install' to set up the proxy.")


@mcp_proxy.command("status")
@click.option(
    "--config",
    "config_path",
    default=None,
    envvar="COPIUM_PROXY_CONFIG",
    help="Path to proxy config file.",
)
def proxy_status(config_path: str | None) -> None:
    """Show MCP proxy configuration and compression stats."""
    from pathlib import Path

    from copium.mcp_proxy.config import ProxyConfig
    from copium.mcp_proxy.installers import detect_agents

    # Load config
    default_config = Path.home() / ".copium" / "mcp-proxy.json"
    if config_path:
        config = ProxyConfig.from_file(config_path)
    elif default_config.exists():
        config = ProxyConfig.from_file(default_config)
    else:
        config = ProxyConfig()

    click.echo("Copium MCP Proxy Status")
    click.echo("=" * 40)

    # Config info
    click.echo(f"\nCompression Settings:")
    click.echo(f"  Descriptions:         {'✓' if config.compression.descriptions else '✗'}")
    click.echo(f"  Schemas:              {'✓' if config.compression.schemas else '✗'}")
    click.echo(f"  Responses:            {'✓' if config.compression.responses else '✗'}")
    click.echo(f"  Progressive Disclosure: {'✓' if config.compression.progressive_disclosure else '✗'}")
    click.echo(f"  Session Dedup:        {'✓' if config.compression.session_dedup else '✗'}")

    # Upstream servers
    click.echo(f"\nUpstream Servers: {len(config.upstream_servers)}")
    for server in config.upstream_servers:
        status = "enabled" if server.enabled else "disabled"
        click.echo(f"  • {server.name} ({status})")

    # Agent detection
    agents = detect_agents()
    click.echo(f"\nDetected Agents: {len(agents)}")
    for agent in agents:
        proxy_status_str = "proxy installed" if agent.installed else "no proxy"
        click.echo(f"  • {agent.name} ({proxy_status_str})")
