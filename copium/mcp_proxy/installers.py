"""Agent detection and MCP proxy installation.

Detects installed AI coding tools and installs the Copium MCP proxy
into their configuration. Supports Claude Code, Cursor, Codex,
Continue, and Zed.
"""

from __future__ import annotations

import json
import logging
import os
import platform
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("copium.mcp_proxy.installers")


@dataclass
class DetectedAgent:
    """An AI coding tool detected on the system."""

    name: str
    config_path: Path
    config_format: str
    servers: dict[str, Any] = field(default_factory=dict)
    installed: bool = False


@dataclass
class InstallResult:
    """Result of installing the proxy into an agent."""

    agent: str
    success: bool
    message: str
    backup_path: Path | None = None


def detect_agents() -> list[DetectedAgent]:
    """Detect installed MCP-capable AI coding tools."""
    agents: list[DetectedAgent] = []

    # Claude Code
    claude_mcp = Path.home() / ".claude" / "mcp.json"
    if claude_mcp.exists():
        agents.append(_load_agent("claude-code", claude_mcp, "mcp.json"))

    # Claude Desktop (macOS)
    if platform.system() == "Darwin":
        desktop_config = (
            Path.home()
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
        if desktop_config.exists():
            agents.append(
                _load_agent("claude-desktop", desktop_config, "claude_desktop.json")
            )

    # Claude Desktop (Linux)
    linux_desktop = Path.home() / ".config" / "claude" / "claude_desktop_config.json"
    if linux_desktop.exists():
        agents.append(
            _load_agent("claude-desktop", linux_desktop, "claude_desktop.json")
        )

    # Cursor
    cursor_config = Path.home() / ".cursor" / "mcp.json"
    if cursor_config.exists():
        agents.append(_load_agent("cursor", cursor_config, "mcp.json"))

    # Codex
    codex_config = Path.home() / ".codex" / "mcp.json"
    if codex_config.exists():
        agents.append(_load_agent("codex", codex_config, "mcp.json"))

    # Continue.dev
    continue_config = Path.home() / ".continue" / "config.json"
    if continue_config.exists():
        agents.append(
            _load_agent("continue", continue_config, "continue.json")
        )

    # Zed
    zed_config = Path.home() / ".config" / "zed" / "settings.json"
    if zed_config.exists():
        agents.append(_load_agent("zed", zed_config, "zed.json"))

    return agents


def install_proxy(
    agent_name: str | None = None,
    config_path: str | None = None,
) -> list[InstallResult]:
    """Install the Copium MCP proxy into detected agents.

    Args:
        agent_name: Specific agent to install for (None = all detected).
        config_path: Optional path to proxy config file.

    Returns:
        List of installation results.
    """
    agents = detect_agents()
    results: list[InstallResult] = []

    if agent_name:
        agents = [a for a in agents if a.name == agent_name]
        if not agents:
            results.append(
                InstallResult(
                    agent=agent_name,
                    success=False,
                    message=f"Agent '{agent_name}' not detected on this system.",
                )
            )
            return results

    for agent in agents:
        result = _install_for_agent(agent, config_path)
        results.append(result)

    return results


def uninstall_proxy(agent_name: str | None = None) -> list[InstallResult]:
    """Remove the Copium MCP proxy from agent configs.

    Args:
        agent_name: Specific agent to uninstall from (None = all).

    Returns:
        List of uninstallation results.
    """
    agents = detect_agents()
    results: list[InstallResult] = []

    if agent_name:
        agents = [a for a in agents if a.name == agent_name]

    for agent in agents:
        result = _uninstall_for_agent(agent)
        results.append(result)

    return results


def _load_agent(name: str, config_path: Path, fmt: str) -> DetectedAgent:
    """Load agent config and extract server info."""
    servers: dict[str, Any] = {}
    try:
        data = json.loads(config_path.read_text())
        servers = data.get("mcpServers", {})
    except (json.JSONDecodeError, OSError):
        pass

    return DetectedAgent(
        name=name,
        config_path=config_path,
        config_format=fmt,
        servers=servers,
        installed="copium-proxy" in servers,
    )


def _install_for_agent(
    agent: DetectedAgent, config_path: str | None
) -> InstallResult:
    """Install proxy into a specific agent's config."""
    if agent.installed:
        return InstallResult(
            agent=agent.name,
            success=True,
            message="Copium proxy already installed.",
        )

    try:
        # Read existing config
        config_data = json.loads(agent.config_path.read_text())
    except (json.JSONDecodeError, OSError):
        config_data = {"mcpServers": {}}

    # Backup original
    backup_path = agent.config_path.with_suffix(".bak")
    agent.config_path.rename(backup_path) if agent.config_path.exists() else None
    if backup_path.exists():
        # Restore original to read, we only rename for backup
        import shutil
        shutil.copy2(backup_path, agent.config_path)

    # Build proxy server entry
    proxy_args = ["mcp", "proxy", "serve"]
    if config_path:
        proxy_args.extend(["--config", config_path])

    proxy_entry = {
        "command": "copium",
        "args": proxy_args,
    }

    # Add env if proxy config path specified
    env: dict[str, str] = {}
    if config_path:
        env["COPIUM_PROXY_CONFIG"] = config_path
    if env:
        proxy_entry["env"] = env

    # Add to config
    if "mcpServers" not in config_data:
        config_data["mcpServers"] = {}
    config_data["mcpServers"]["copium-proxy"] = proxy_entry

    # Write config
    agent.config_path.parent.mkdir(parents=True, exist_ok=True)
    agent.config_path.write_text(json.dumps(config_data, indent=2) + "\n")

    # Generate proxy config with upstream servers
    _generate_proxy_config(agent, config_path)

    return InstallResult(
        agent=agent.name,
        success=True,
        message=f"Installed copium-proxy into {agent.config_path}",
        backup_path=backup_path if backup_path.exists() else None,
    )


def _uninstall_for_agent(agent: DetectedAgent) -> InstallResult:
    """Remove proxy from a specific agent's config."""
    if not agent.installed:
        return InstallResult(
            agent=agent.name,
            success=True,
            message="Copium proxy not installed.",
        )

    try:
        config_data = json.loads(agent.config_path.read_text())
        config_data.get("mcpServers", {}).pop("copium-proxy", None)
        agent.config_path.write_text(json.dumps(config_data, indent=2) + "\n")

        return InstallResult(
            agent=agent.name,
            success=True,
            message=f"Removed copium-proxy from {agent.config_path}",
        )
    except (json.JSONDecodeError, OSError) as e:
        return InstallResult(
            agent=agent.name,
            success=False,
            message=f"Failed to uninstall: {e}",
        )


def _generate_proxy_config(agent: DetectedAgent, config_path: str | None) -> None:
    """Generate a proxy config file with the agent's existing servers as upstreams."""
    from copium.mcp_proxy.config import ProxyConfig, UpstreamServerConfig

    # Use agent's existing MCP servers as upstreams
    upstreams = []
    for name, server_data in agent.servers.items():
        if name == "copium-proxy":
            continue
        if isinstance(server_data, dict):
            upstreams.append(
                UpstreamServerConfig(
                    name=name,
                    command=server_data.get("command", ""),
                    args=server_data.get("args", []),
                    env=server_data.get("env", {}),
                )
            )

    proxy_config = ProxyConfig(upstream_servers=upstreams)

    # Save to default location
    proxy_config_path = Path(
        config_path or str(Path.home() / ".copium" / "mcp-proxy.json")
    )
    proxy_config.save(proxy_config_path)
    logger.info(f"Generated proxy config: {proxy_config_path}")
