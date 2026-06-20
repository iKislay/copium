"""Enhanced MCP Server with copium_compress, copium_retrieve, copium_stats tools.

Exposes Copium's compression capabilities as MCP tools for
Claude Code / Codex integration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from copium.config import CopiumConfig


@dataclass
class MCPToolDefinition:
    """Definition of an MCP tool."""

    name: str
    description: str
    input_schema: dict[str, Any]


# Tool definitions for MCP
MCP_TOOLS: list[MCPToolDefinition] = [
    MCPToolDefinition(
        name="copium_compress",
        description="Compress tool outputs to reduce token usage. Use after receiving large tool outputs to save context window space.",
        input_schema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The tool output content to compress",
                },
                "tool_name": {
                    "type": "string",
                    "description": "Name of the tool that produced this output",
                },
                "query": {
                    "type": "string",
                    "description": "Optional user query for relevance scoring",
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Maximum tokens in compressed output (default: 1000)",
                    "default": 1000,
                },
            },
            "required": ["content"],
        },
    ),
    MCPToolDefinition(
        name="copium_retrieve",
        description="Retrieve compressed context from Copium's memory store. Use when you need historical context or previously compressed data.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for retrieving relevant context",
                },
                "max_items": {
                    "type": "integer",
                    "description": "Maximum number of items to retrieve (default: 5)",
                    "default": 5,
                },
                "min_relevance": {
                    "type": "number",
                    "description": "Minimum relevance score (0-1, default: 0.3)",
                    "default": 0.3,
                },
            },
            "required": ["query"],
        },
    ),
    MCPToolDefinition(
        name="copium_stats",
        description="Get compression statistics and savings metrics. Use to check how much context you've saved.",
        input_schema={
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "description": "Time period: 'session', 'hour', 'day', 'all' (default: 'session')",
                    "enum": ["session", "hour", "day", "all"],
                    "default": "session",
                },
            },
        },
    ),
]


class CopiumMCPServer:
    """Enhanced MCP server with Copium tools.

    Provides copium_compress, copium_retrieve, copium_stats as MCP tools.
    """

    def __init__(self, config: CopiumConfig | None = None) -> None:
        self.config = config or CopiumConfig()
        self._session_stats: dict[str, Any] = {
            "compressions": 0,
            "tokens_saved": 0,
            "requests": 0,
        }

    def get_tools(self) -> list[dict[str, Any]]:
        """Get tool definitions for MCP."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
            }
            for tool in MCP_TOOLS
        ]

    def compress(self, content: str, tool_name: str = "", query: str = "", max_tokens: int = 1000) -> str:
        """Compress tool output content."""
        from copium.transforms.smart_crusher import SmartCrusher
        from copium.tokenizer import Tokenizer
        from copium.tokenizers.estimator import EstimatingTokenCounter

        tokenizer = Tokenizer(EstimatingTokenCounter())
        crusher = SmartCrusher()

        # Wrap content in message format
        messages = [{"role": "tool", "content": content}]

        # Estimate original tokens
        original_tokens = tokenizer.count_text(content)

        # Compress
        result = crusher.apply(messages, tokenizer)

        # Get compressed content
        compressed = result.messages[0].get("content", content) if result.messages else content
        compressed_tokens = tokenizer.count_text(compressed)

        # Update session stats
        self._session_stats["compressions"] += 1
        self._session_stats["tokens_saved"] += original_tokens - compressed_tokens

        return compressed

    def retrieve(self, query: str, max_items: int = 5, min_relevance: float = 0.3) -> str:
        """Retrieve compressed context from memory store."""
        # Placeholder for memory retrieval
        # In production, this would query the memory database
        return json.dumps({
            "query": query,
            "items": [],
            "message": "Memory retrieval not configured. Use copium memory commands to manage memories.",
        })

    def stats(self, period: str = "session") -> str:
        """Get compression statistics."""
        stats = {
            "period": period,
            "compressions": self._session_stats["compressions"],
            "tokens_saved": self._session_stats["tokens_saved"],
            "estimated_cost_saved": f"${self._session_stats['tokens_saved'] * 0.002 / 1000:.4f}",
        }

        return json.dumps(stats, indent=2)

    def handle_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Handle an MCP tool call."""
        if tool_name == "copium_compress":
            return self.compress(
                content=arguments.get("content", ""),
                tool_name=arguments.get("tool_name", ""),
                query=arguments.get("query", ""),
                max_tokens=arguments.get("max_tokens", 1000),
            )
        elif tool_name == "copium_retrieve":
            return self.retrieve(
                query=arguments.get("query", ""),
                max_items=arguments.get("max_items", 5),
                min_relevance=arguments.get("min_relevance", 0.3),
            )
        elif tool_name == "copium_stats":
            return self.stats(period=arguments.get("period", "session"))
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
