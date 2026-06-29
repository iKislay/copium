"""Main Copium MCP Proxy server.

The proxy sits between AI coding tools and upstream MCP servers,
transparently compressing tool descriptions, schemas, and responses.
Speaks standard MCP protocol on both sides (stdio transport).

Architecture:
    Agent → CopiumMCPProxy (this module) → Upstream MCP Servers
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from copium.mcp_proxy.cache import ProxyCache
from copium.mcp_proxy.config import ProxyConfig
from copium.mcp_proxy.description_compressor import DescriptionCompressor
from copium.mcp_proxy.progressive import ProgressiveDisclosure
from copium.mcp_proxy.response_compressor import ResponseCompressor
from copium.mcp_proxy.schema_compressor import SchemaCompressor
from copium.mcp_proxy.session_dedup import SessionDedup
from copium.mcp_proxy.upstream import UpstreamManager

logger = logging.getLogger("copium.mcp_proxy")


@dataclass
class ProxyMetrics:
    """Runtime metrics for the proxy."""

    start_time: float = field(default_factory=time.time)
    tools_listed: int = 0
    tools_called: int = 0
    total_original_tokens: int = 0
    total_compressed_tokens: int = 0
    dedup_hits: int = 0

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self.start_time

    @property
    def savings_percent(self) -> float:
        if self.total_original_tokens == 0:
            return 0.0
        return (
            (1 - self.total_compressed_tokens / self.total_original_tokens)
            * 100
        )


class CopiumMCPProxy:
    """Transparent MCP compression proxy.

    Intercepts MCP protocol messages between an AI coding tool and
    upstream MCP servers. Applies compression transparently:

    - tools/list → compress descriptions + schemas
    - tools/call → compress responses + dedup
    - Progressive disclosure → stubs first, full on demand

    Usage:
        config = ProxyConfig.from_file("~/.copium/mcp-proxy.yaml")
        proxy = CopiumMCPProxy(config)
        await proxy.serve()
    """

    def __init__(self, config: ProxyConfig) -> None:
        self.config = config

        # Compression engines
        self.description_compressor = DescriptionCompressor(
            max_description_tokens=config.compression.max_description_tokens,
        )
        self.schema_compressor = SchemaCompressor()
        self.response_compressor = ResponseCompressor(
            min_tokens_to_compress=config.compression.min_response_tokens,
            ccr_enabled=config.ccr_enabled,
        )
        self.session_dedup = SessionDedup()
        self.progressive = ProgressiveDisclosure()

        # Infrastructure
        self.upstream = UpstreamManager(config.upstream_servers)
        self.cache = ProxyCache(default_ttl=config.cache_ttl_seconds)
        self.metrics = ProxyMetrics()

        self._server: Any = None

    async def serve(self) -> None:
        """Start the MCP proxy server (stdio transport).

        This is the main entry point. Launches upstream servers,
        discovers tools, then serves MCP protocol to the agent.
        """
        try:
            from mcp.server import Server
            from mcp.server.stdio import stdio_server
            from mcp.types import TextContent, Tool
        except ImportError:
            raise ImportError(
                "MCP SDK required for proxy. Install with: pip install mcp"
            )

        # Start upstream servers
        logger.info("Starting upstream MCP servers...")
        await self.upstream.start_all()

        # Discover all tools
        upstream_tools = await self.upstream.list_tools()
        self.progressive.register_tools(upstream_tools)
        logger.info(
            f"Discovered {len(upstream_tools)} tools from "
            f"{len(self.upstream.connected_servers)} servers"
        )

        # Create MCP server
        server = Server("copium-mcp-proxy")
        self._server = server

        @server.list_tools()
        async def handle_list_tools() -> list[Tool]:
            """Handle tools/list — return compressed tool definitions."""
            self.metrics.tools_listed += 1
            return self._build_tool_list(Tool)

        @server.call_tool()
        async def handle_call_tool(
            name: str, arguments: dict[str, Any] | None
        ) -> list[TextContent]:
            """Handle tools/call — compress responses."""
            self.metrics.tools_called += 1
            arguments = arguments or {}

            # Handle proxy-internal tools
            if name == "copium_find_tool":
                result = self._handle_find_tool(arguments)
                return [TextContent(type="text", text=result)]

            if name == "copium_get_tool_schema":
                result = self._handle_get_schema(arguments)
                return [TextContent(type="text", text=result)]

            if name == "copium_retrieve":
                result = self._handle_retrieve(arguments)
                return [TextContent(type="text", text=result)]

            if name == "copium_proxy_stats":
                result = self._handle_stats()
                return [TextContent(type="text", text=result)]

            # Forward to upstream and compress response
            result = await self._forward_and_compress(name, arguments)
            return [TextContent(type="text", text=result)]

        # Run server
        logger.info("Copium MCP Proxy ready")
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    async def shutdown(self) -> None:
        """Gracefully shut down the proxy."""
        await self.upstream.stop_all()
        logger.info("Proxy shut down")

    def _build_tool_list(self, Tool: type) -> list[Any]:
        """Build the tool list to send to the agent."""
        tools = []

        # Progressive disclosure: send stubs if enabled
        if self.config.compression.progressive_disclosure:
            # Add proxy discovery tools
            tools.extend(self._get_proxy_tools(Tool))

            # Add compressed stubs for all upstream tools
            for stub in self.progressive.get_stubs():
                tools.append(
                    Tool(
                        name=stub.name,
                        description=stub.short_description,
                        inputSchema={"type": "object", "properties": {}},
                    )
                )
        else:
            # No progressive disclosure: send compressed but full definitions
            tools.extend(self._get_proxy_tools(Tool))
            for tool_def in self.progressive._tools:
                if self.config.compression.descriptions:
                    compressed = self.description_compressor.compress({
                        "name": tool_def.name,
                        "description": tool_def.description,
                        "inputSchema": tool_def.input_schema,
                    })
                    desc = compressed.description
                    schema = compressed.input_schema
                else:
                    desc = tool_def.description
                    schema = tool_def.input_schema

                if self.config.compression.schemas:
                    result = self.schema_compressor.compress(schema)
                    schema = result.compressed

                tools.append(
                    Tool(
                        name=tool_def.name,
                        description=desc,
                        inputSchema=schema,
                    )
                )

        return tools

    def _get_proxy_tools(self, Tool: type) -> list[Any]:
        """Get the proxy's own tools (find_tool, get_schema, retrieve, stats)."""
        return [
            Tool(
                name="copium_find_tool",
                description="Search available tools by what you need to do.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "What you need to do",
                        },
                        "category": {
                            "type": "string",
                            "description": "Optional: filesystem, search, git, database, web, code",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="copium_get_tool_schema",
                description="Get full parameter schema for a tool.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tool_name": {
                            "type": "string",
                            "description": "Name of the tool",
                        },
                    },
                    "required": ["tool_name"],
                },
            ),
            Tool(
                name="copium_retrieve",
                description="Retrieve full uncompressed content by hash.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "hash": {
                            "type": "string",
                            "description": "Hash from compressed response",
                        },
                    },
                    "required": ["hash"],
                },
            ),
            Tool(
                name="copium_proxy_stats",
                description="Show proxy compression statistics.",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
        ]

    def _handle_find_tool(self, arguments: dict[str, Any]) -> str:
        """Handle copium_find_tool calls."""
        import json

        query = arguments.get("query", "")
        category = arguments.get("category")
        results = self.progressive.find_tools(query, category)

        if not results:
            return f"No tools found matching '{query}'. Try a different query."

        return json.dumps(results, indent=2)

    def _handle_get_schema(self, arguments: dict[str, Any]) -> str:
        """Handle copium_get_tool_schema calls."""
        import json

        tool_name = arguments.get("tool_name", "")
        schema = self.progressive.get_full_schema(tool_name)

        if not schema:
            return f"Tool '{tool_name}' not found."

        return json.dumps(schema, indent=2)

    def _handle_retrieve(self, arguments: dict[str, Any]) -> str:
        """Handle copium_retrieve calls."""
        hash_prefix = arguments.get("hash", "")
        content = self.response_compressor.retrieve(hash_prefix)

        if content is None:
            return f"No content found for hash '{hash_prefix}'."

        return content

    def _handle_stats(self) -> str:
        """Handle copium_proxy_stats calls."""
        import json

        stats = {
            "proxy": {
                "uptime_seconds": round(self.metrics.uptime_seconds, 1),
                "tools_listed": self.metrics.tools_listed,
                "tools_called": self.metrics.tools_called,
                "total_savings_percent": round(self.metrics.savings_percent, 1),
            },
            "description_compressor": self.description_compressor.stats,
            "schema_compressor": self.schema_compressor.stats,
            "response_compressor": self.response_compressor.stats,
            "session_dedup": self.session_dedup.stats,
            "progressive": self.progressive.stats,
            "cache": self.cache.stats,
            "upstream": {
                "connected_servers": self.upstream.connected_servers,
                "total_tools": self.upstream.total_tools,
            },
        }
        return json.dumps(stats, indent=2)

    async def _forward_and_compress(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> str:
        """Forward a tool call to upstream, then compress the response."""
        # Execute on upstream
        raw_result = await self.upstream.call_tool(tool_name, arguments)

        # Check dedup
        if self.config.compression.session_dedup:
            dedup_marker = self.session_dedup.check_call(
                tool_name, arguments, raw_result
            )
            if dedup_marker:
                self.metrics.dedup_hits += 1
                return dedup_marker

        # Compress response
        if self.config.compression.responses:
            compressed = self.response_compressor.compress(tool_name, raw_result)
            self.metrics.total_original_tokens += compressed.original_tokens
            self.metrics.total_compressed_tokens += compressed.compressed_tokens
            return compressed.content

        # No compression
        est_tokens = int(len(raw_result.split()) * 1.3)
        self.metrics.total_original_tokens += est_tokens
        self.metrics.total_compressed_tokens += est_tokens
        return raw_result
