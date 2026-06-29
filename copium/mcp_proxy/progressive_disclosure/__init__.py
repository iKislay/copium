"""Progressive Tool Disclosure for MCP Proxy.

Implements transparent progressive tool disclosure that reduces MCP tool
token consumption by 70-98% without any client changes.

Architecture:
    1. Schema Registry — indexes all tool schemas
    2. Eager/Deferred Split — classifies tools by usage patterns
    3. Meta-Tools — copium_find_tool + copium_call_tool
    4. BM25 Search — fast tool discovery by natural language query
    5. System Prompt Injection — teaches LLM the two-step pattern

Usage:
    from copium.mcp_proxy.progressive_disclosure import (
        ProgressiveDisclosureEngine,
        ToolSchemaRegistry,
        EagerLoadingPolicy,
    )

    registry = ToolSchemaRegistry()
    for tool in tools:
        registry.register(tool)

    engine = ProgressiveDisclosureEngine(registry)
    eager_tools, meta_tools = engine.process_tools(tools)
"""

from copium.mcp_proxy.progressive_disclosure.registry import (
    ToolEntry,
    ToolSchemaRegistry,
)
from copium.mcp_proxy.progressive_disclosure.eager_policy import EagerLoadingPolicy
from copium.mcp_proxy.progressive_disclosure.meta_tools import (
    COPIUM_CALL_TOOL,
    COPIUM_FIND_TOOL,
    build_tool_list_summary,
)
from copium.mcp_proxy.progressive_disclosure.engine import ProgressiveDisclosureEngine
from copium.mcp_proxy.progressive_disclosure.config import ProgressiveDisclosureConfig

__all__ = [
    "COPIUM_CALL_TOOL",
    "COPIUM_FIND_TOOL",
    "EagerLoadingPolicy",
    "ProgressiveDisclosureConfig",
    "ProgressiveDisclosureEngine",
    "ToolEntry",
    "ToolSchemaRegistry",
    "build_tool_list_summary",
]
