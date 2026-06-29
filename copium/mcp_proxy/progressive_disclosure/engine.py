"""Progressive Disclosure Engine — orchestrates the full pipeline.

The engine ties together the registry, eager policy, BM25 search,
and meta-tools to provide a single entry point for progressive
tool disclosure in the proxy.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from copium.mcp_proxy.progressive_disclosure.config import ProgressiveDisclosureConfig
from copium.mcp_proxy.progressive_disclosure.eager_policy import EagerLoadingPolicy
from copium.mcp_proxy.progressive_disclosure.meta_tools import (
    COPIUM_CALL_TOOL,
    COPIUM_FIND_TOOL,
)
from copium.mcp_proxy.progressive_disclosure.prompt_injection import (
    build_system_prompt_fragment,
)
from copium.mcp_proxy.progressive_disclosure.registry import ToolEntry, ToolSchemaRegistry
from copium.mcp_proxy.progressive_disclosure.search import BM25Index, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class DisclosureResult:
    """Result of processing tools through progressive disclosure."""

    tools_for_llm: list[dict[str, Any]]
    """Tools to send to the LLM (eager + meta-tools)."""

    system_prompt_fragment: str
    """System prompt fragment to inject."""

    total_tools: int = 0
    eager_count: int = 0
    deferred_count: int = 0
    original_tokens: int = 0
    disclosed_tokens: int = 0

    @property
    def savings_pct(self) -> float:
        if self.original_tokens == 0:
            return 0.0
        return ((self.original_tokens - self.disclosed_tokens) / self.original_tokens) * 100


@dataclass
class FindToolResult:
    """Result of a copium_find_tool call."""

    tools: list[dict[str, Any]]
    """Matching tools with name, description, and schema."""

    query: str = ""
    total_available: int = 0


@dataclass
class CallToolResult:
    """Result of processing a copium_call_tool request."""

    tool_name: str
    arguments: dict[str, Any]
    original_definition: dict[str, Any] | None = None
    error: str | None = None


class ProgressiveDisclosureEngine:
    """Orchestrates progressive tool disclosure.

    Usage:
        engine = ProgressiveDisclosureEngine()
        engine.register_tools(tools_from_request)
        result = engine.process()
        # result.tools_for_llm -> send to LLM
        # result.system_prompt_fragment -> inject into system message
    """

    def __init__(
        self,
        config: ProgressiveDisclosureConfig | None = None,
    ) -> None:
        self._config = config or ProgressiveDisclosureConfig()
        self._registry = ToolSchemaRegistry()
        self._policy = EagerLoadingPolicy(self._config)
        self._search_index = BM25Index()
        self._schema_cache: dict[str, dict[str, Any]] = {}

    @property
    def registry(self) -> ToolSchemaRegistry:
        return self._registry

    @property
    def config(self) -> ProgressiveDisclosureConfig:
        return self._config

    def register_tools(self, tools: list[dict[str, Any]]) -> None:
        """Register all tools from an incoming request.

        Args:
            tools: List of tool definitions (OpenAI or Anthropic format).
        """
        self._registry.clear()
        self._search_index.clear()
        self._schema_cache.clear()

        for tool in tools:
            # Handle OpenAI function-call format
            if "function" in tool:
                func = tool["function"]
                normalized = {
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {}),
                }
            else:
                normalized = tool

            tool_id = self._registry.register(normalized)
            entry = self._registry.get_by_id(tool_id)
            if entry:
                self._schema_cache[entry.name] = tool
                self._search_index.index_tool(
                    name=entry.name,
                    description=entry.description,
                    parameters=entry.schema,
                    summary=entry.summary,
                )

    def process(self) -> DisclosureResult:
        """Process registered tools through progressive disclosure.

        Returns:
            DisclosureResult with tools_for_llm and system_prompt_fragment.
        """
        all_entries = self._registry.all_entries()
        total = len(all_entries)

        # If below threshold, don't apply progressive disclosure
        if total < self._config.min_tools_for_disclosure:
            all_tools = [
                self._schema_cache[e.name]
                for e in all_entries
                if e.name in self._schema_cache
            ]
            return DisclosureResult(
                tools_for_llm=all_tools,
                system_prompt_fragment="",
                total_tools=total,
                eager_count=total,
                deferred_count=0,
                original_tokens=self._registry.total_token_estimate,
                disclosed_tokens=self._registry.total_token_estimate,
            )

        # Classify tools
        eager, deferred = self._policy.classify(all_entries)

        # Build tool list for LLM: eager tools + meta-tools
        tools_for_llm: list[dict[str, Any]] = []

        for entry in eager:
            if entry.name in self._schema_cache:
                tools_for_llm.append(self._schema_cache[entry.name])

        # Add meta-tools
        tools_for_llm.append(COPIUM_FIND_TOOL)
        tools_for_llm.append(COPIUM_CALL_TOOL)

        # Generate system prompt fragment
        prompt_fragment = build_system_prompt_fragment(
            eager_tools=eager,
            deferred_count=len(deferred),
            total_tools=total,
        )

        # Calculate token estimates
        original_tokens = self._registry.total_token_estimate
        disclosed_tokens = sum(
            e.token_estimate for e in eager
        ) + 200  # ~200 tokens for meta-tool schemas

        logger.info(
            "Progressive disclosure: %d/%d tools eager, %d deferred, "
            "%.1f%% token savings",
            len(eager), total, len(deferred),
            ((original_tokens - disclosed_tokens) / max(original_tokens, 1)) * 100,
        )

        return DisclosureResult(
            tools_for_llm=tools_for_llm,
            system_prompt_fragment=prompt_fragment,
            total_tools=total,
            eager_count=len(eager),
            deferred_count=len(deferred),
            original_tokens=original_tokens,
            disclosed_tokens=disclosed_tokens,
        )

    def handle_find_tool(self, arguments: dict[str, Any]) -> FindToolResult:
        """Handle a copium_find_tool call from the LLM.

        Args:
            arguments: The arguments from the tool call (query, limit).

        Returns:
            FindToolResult with matching tools.
        """
        query = arguments.get("query", "")
        limit = arguments.get("limit", self._config.search_top_k)

        results = self._search_index.search(query, top_k=limit)

        tools: list[dict[str, Any]] = []
        for result in results:
            entry = self._registry.get_by_name(result.tool_name)
            if entry:
                tools.append({
                    "name": entry.name,
                    "description": entry.description,
                    "input_schema": entry.schema,
                    "relevance_score": round(result.score, 3),
                })

        return FindToolResult(
            tools=tools,
            query=query,
            total_available=self._registry.tool_count,
        )

    def handle_call_tool(self, arguments: dict[str, Any]) -> CallToolResult:
        """Handle a copium_call_tool call from the LLM.

        Args:
            arguments: The arguments (tool_name, arguments).

        Returns:
            CallToolResult with the original definition for dispatch.
        """
        tool_name = arguments.get("tool_name", "")
        tool_args = arguments.get("arguments", {})

        entry = self._registry.get_by_name(tool_name)
        if entry is None:
            return CallToolResult(
                tool_name=tool_name,
                arguments=tool_args,
                error=f"Tool '{tool_name}' not found. Use copium_find_tool to discover available tools.",
            )

        # Record the call
        self._registry.record_call(tool_name)

        original = self._schema_cache.get(entry.name)
        return CallToolResult(
            tool_name=entry.name,
            arguments=tool_args,
            original_definition=original,
        )

    def format_find_tool_response(self, result: FindToolResult) -> str:
        """Format a FindToolResult as a string response for the LLM."""
        if not result.tools:
            return (
                f"No tools found matching '{result.query}'. "
                f"Try a different query. {result.total_available} tools available."
            )

        lines = [f"Found {len(result.tools)} matching tool(s):\n"]
        for tool in result.tools:
            lines.append(f"**{tool['name']}** (relevance: {tool['relevance_score']})")
            lines.append(f"  {tool['description'][:200]}")
            if tool.get("input_schema"):
                params = tool["input_schema"].get("properties", {})
                required = tool["input_schema"].get("required", [])
                if params:
                    param_strs = []
                    for pname, pdef in list(params.items())[:8]:
                        req_marker = "*" if pname in required else ""
                        ptype = pdef.get("type", "any")
                        param_strs.append(f"{pname}{req_marker}: {ptype}")
                    lines.append(f"  Parameters: {', '.join(param_strs)}")
            lines.append("")

        lines.append("Use copium_call_tool(tool_name=<name>, arguments={...}) to call.")
        return "\n".join(lines)
