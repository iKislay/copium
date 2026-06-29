"""Upstream MCP server management for the proxy.

Manages lifecycle of upstream MCP servers: spawning child processes,
communicating via stdio transport, and forwarding tool calls.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from copium.mcp_proxy.config import UpstreamServerConfig

logger = logging.getLogger("copium.mcp_proxy.upstream")


@dataclass
class ToolDefinition:
    """A tool definition from an upstream server."""

    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str


@dataclass
class UpstreamConnection:
    """Active connection to an upstream MCP server."""

    config: UpstreamServerConfig
    process: asyncio.subprocess.Process | None = None
    tools: list[ToolDefinition] = field(default_factory=list)
    connected: bool = False
    _request_id: int = 0

    def next_id(self) -> int:
        self._request_id += 1
        return self._request_id


class UpstreamManager:
    """Manages connections to upstream MCP servers.

    Handles:
    - Spawning server processes
    - MCP protocol initialization
    - Tool discovery (tools/list)
    - Tool execution (tools/call)
    - Graceful shutdown
    """

    def __init__(self, servers: list[UpstreamServerConfig]) -> None:
        self._server_configs = servers
        self._connections: dict[str, UpstreamConnection] = {}
        self._tool_map: dict[str, str] = {}  # tool_name -> server_name

    async def start_all(self) -> None:
        """Start all configured upstream servers."""
        for config in self._server_configs:
            if not config.enabled:
                continue
            try:
                await self._start_server(config)
            except Exception as e:
                logger.error(f"Failed to start upstream '{config.name}': {e}")

    async def stop_all(self) -> None:
        """Gracefully stop all upstream servers."""
        for name, conn in self._connections.items():
            try:
                await self._stop_server(conn)
            except Exception as e:
                logger.warning(f"Error stopping '{name}': {e}")
        self._connections.clear()
        self._tool_map.clear()

    async def list_tools(self) -> list[ToolDefinition]:
        """Get all tools from all connected upstream servers."""
        all_tools: list[ToolDefinition] = []
        for name, conn in self._connections.items():
            if conn.connected:
                tools = await self._fetch_tools(conn)
                conn.tools = tools
                all_tools.extend(tools)
                for tool in tools:
                    self._tool_map[tool.name] = name
        return all_tools

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> str:
        """Call a tool on the appropriate upstream server.

        Args:
            tool_name: Name of the tool to call.
            arguments: Arguments to pass to the tool.

        Returns:
            Tool result as a string.

        Raises:
            ValueError: If the tool is not found in any upstream server.
        """
        server_name = self._tool_map.get(tool_name)
        if not server_name:
            raise ValueError(
                f"Tool '{tool_name}' not found in any upstream server"
            )

        conn = self._connections.get(server_name)
        if not conn or not conn.connected:
            raise ValueError(
                f"Upstream server '{server_name}' is not connected"
            )

        return await self._execute_tool(conn, tool_name, arguments)

    def get_server_for_tool(self, tool_name: str) -> str | None:
        """Get the server name that hosts a given tool."""
        return self._tool_map.get(tool_name)

    @property
    def connected_servers(self) -> list[str]:
        """List of connected server names."""
        return [
            name
            for name, conn in self._connections.items()
            if conn.connected
        ]

    @property
    def total_tools(self) -> int:
        """Total number of tools across all servers."""
        return len(self._tool_map)

    async def _start_server(self, config: UpstreamServerConfig) -> None:
        """Start a single upstream server process."""
        import os

        env = {**os.environ, **config.env}

        cmd = [config.command] + config.args
        logger.info(f"Starting upstream '{config.name}': {' '.join(cmd)}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        conn = UpstreamConnection(config=config, process=process)
        self._connections[config.name] = conn

        # Initialize MCP protocol
        await self._initialize(conn)
        conn.connected = True
        logger.info(f"Upstream '{config.name}' connected")

    async def _stop_server(self, conn: UpstreamConnection) -> None:
        """Stop an upstream server process."""
        if conn.process and conn.process.returncode is None:
            conn.process.terminate()
            try:
                await asyncio.wait_for(conn.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                conn.process.kill()
        conn.connected = False

    async def _initialize(self, conn: UpstreamConnection) -> None:
        """Send MCP initialize request to upstream server."""
        request = {
            "jsonrpc": "2.0",
            "id": conn.next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "copium-mcp-proxy",
                    "version": "1.0.0",
                },
            },
        }
        response = await self._send_request(conn, request)

        # Send initialized notification
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        await self._send_notification(conn, notification)

        return response

    async def _fetch_tools(self, conn: UpstreamConnection) -> list[ToolDefinition]:
        """Fetch tools/list from an upstream server."""
        request = {
            "jsonrpc": "2.0",
            "id": conn.next_id(),
            "method": "tools/list",
            "params": {},
        }
        response = await self._send_request(conn, request)

        tools = []
        for tool_data in response.get("result", {}).get("tools", []):
            tools.append(
                ToolDefinition(
                    name=tool_data.get("name", ""),
                    description=tool_data.get("description", ""),
                    input_schema=tool_data.get("inputSchema", {}),
                    server_name=conn.config.name,
                )
            )
        return tools

    async def _execute_tool(
        self,
        conn: UpstreamConnection,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        """Execute a tool call on an upstream server."""
        request = {
            "jsonrpc": "2.0",
            "id": conn.next_id(),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }
        response = await self._send_request(conn, request)

        # Extract text content from result
        result = response.get("result", {})
        content = result.get("content", [])
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
            return "\n".join(text_parts)
        return str(content)

    async def _send_request(
        self, conn: UpstreamConnection, request: dict[str, Any]
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for response."""
        if not conn.process or not conn.process.stdin or not conn.process.stdout:
            raise ConnectionError(
                f"No active connection to '{conn.config.name}'"
            )

        message = json.dumps(request) + "\n"
        conn.process.stdin.write(message.encode())
        await conn.process.stdin.drain()

        # Read response line
        line = await conn.process.stdout.readline()
        if not line:
            raise ConnectionError(
                f"Connection closed by '{conn.config.name}'"
            )

        return json.loads(line.decode())

    async def _send_notification(
        self, conn: UpstreamConnection, notification: dict[str, Any]
    ) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not conn.process or not conn.process.stdin:
            return

        message = json.dumps(notification) + "\n"
        conn.process.stdin.write(message.encode())
        await conn.process.stdin.drain()
