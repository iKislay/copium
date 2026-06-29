"""Meta-tool definitions for progressive tool disclosure.

Defines copium_find_tool and copium_call_tool — the two meta-tools
injected into the LLM request to replace the full tool set.
"""

from __future__ import annotations

from typing import Any

from copium.mcp_proxy.progressive_disclosure.registry import ToolEntry


# The find_tool meta-tool exposed to the LLM
COPIUM_FIND_TOOL: dict[str, Any] = {
    "name": "copium_find_tool",
    "description": (
        "Search for available tools by describing what you need. "
        "Returns matching tool names and their parameter schemas. "
        "Use this before calling copium_call_tool to discover the right tool."
    ),
    "input_schema": {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Natural language description of what you want to do. "
                    "Example: 'create a GitHub issue' or 'search files by content'"
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of tools to return (default: 3).",
                "default": 3,
            },
        },
    },
}

# The call_tool meta-tool exposed to the LLM
COPIUM_CALL_TOOL: dict[str, Any] = {
    "name": "copium_call_tool",
    "description": (
        "Call a tool by name with arguments. Use copium_find_tool first "
        "to discover the tool name and required parameters."
    ),
    "input_schema": {
        "type": "object",
        "required": ["tool_name", "arguments"],
        "properties": {
            "tool_name": {
                "type": "string",
                "description": "The exact name of the tool to call (from copium_find_tool results).",
            },
            "arguments": {
                "type": "object",
                "description": "Arguments to pass to the tool, matching the schema returned by copium_find_tool.",
            },
        },
    },
}


def build_tool_list_summary(
    eager_tools: list[ToolEntry],
    deferred_count: int,
) -> str:
    """Build a compact summary of available tools for the system prompt.

    Args:
        eager_tools: Tools loaded eagerly (full schema available).
        deferred_count: Number of deferred tools (available via find_tool).

    Returns:
        Formatted string for system prompt injection.
    """
    lines = []
    lines.append(f"Available tools: {len(eager_tools)} loaded + {deferred_count} discoverable")
    lines.append("")
    lines.append("Loaded tools (call directly):")
    for tool in eager_tools:
        lines.append(f"  - {tool.name}")
    lines.append("")
    lines.append(f"Additional {deferred_count} tools available via copium_find_tool.")
    lines.append("Use copium_find_tool(query=<description>) to discover them.")
    return "\n".join(lines)
