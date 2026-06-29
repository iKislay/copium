"""System prompt injection for progressive tool disclosure.

Generates the system prompt fragment that teaches the LLM to use
copium_find_tool + copium_call_tool for discovering deferred tools.
"""

from __future__ import annotations

from copium.mcp_proxy.progressive_disclosure.registry import ToolEntry


PROGRESSIVE_DISCLOSURE_PROMPT_TEMPLATE = """\
## Tool Discovery

You have access to {total_tools} tools total. {eager_count} are loaded directly \
(call them normally). {deferred_count} additional tools are available on-demand.

To use additional tools:
1. Call copium_find_tool(query="<what you need>") to discover the right tool.
2. Review the returned tool name and parameter schema.
3. Call copium_call_tool(tool_name="<name>", arguments={{...}}) to execute it.

Directly available tools: {eager_tool_names}

For anything else, use copium_find_tool first.\
"""


def build_system_prompt_fragment(
    eager_tools: list[ToolEntry],
    deferred_count: int,
    total_tools: int,
) -> str:
    """Build the system prompt fragment for progressive disclosure.

    Args:
        eager_tools: Tools loaded eagerly.
        deferred_count: Number of deferred tools.
        total_tools: Total tool count.

    Returns:
        System prompt fragment string.
    """
    eager_names = ", ".join(t.name for t in eager_tools[:15])
    if len(eager_tools) > 15:
        eager_names += f", ... (+{len(eager_tools) - 15} more)"

    return PROGRESSIVE_DISCLOSURE_PROMPT_TEMPLATE.format(
        total_tools=total_tools,
        eager_count=len(eager_tools),
        deferred_count=deferred_count,
        eager_tool_names=eager_names,
    )
