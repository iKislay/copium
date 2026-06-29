"""Progressive disclosure interceptor for the LLM proxy.

Intercepts LLM API requests to apply progressive tool disclosure:
1. Strips deferred tools from the tools[] array
2. Injects copium_find_tool + copium_call_tool meta-tools
3. Handles responses containing copium_find_tool/copium_call_tool calls
4. Injects system prompt fragment for the two-step pattern
"""

from __future__ import annotations

import json
import logging
from typing import Any

from copium.mcp_proxy.progressive_disclosure.config import ProgressiveDisclosureConfig
from copium.mcp_proxy.progressive_disclosure.engine import (
    ProgressiveDisclosureEngine,
    DisclosureResult,
)

logger = logging.getLogger(__name__)


class ProgressiveDisclosureInterceptor:
    """Proxy-level interceptor for progressive tool disclosure.

    Sits in the proxy pipeline and transparently applies progressive
    disclosure to LLM API requests. Zero client changes required.

    Usage:
        interceptor = ProgressiveDisclosureInterceptor()
        modified_request = interceptor.intercept_request(request_body)
        # ... send to LLM provider ...
        modified_response = interceptor.intercept_response(response_body)
    """

    def __init__(
        self,
        config: ProgressiveDisclosureConfig | None = None,
    ) -> None:
        self._config = config or ProgressiveDisclosureConfig()
        self._engine = ProgressiveDisclosureEngine(self._config)
        self._last_result: DisclosureResult | None = None

    @property
    def engine(self) -> ProgressiveDisclosureEngine:
        return self._engine

    @property
    def last_result(self) -> DisclosureResult | None:
        return self._last_result

    def intercept_request(self, body: dict[str, Any]) -> dict[str, Any]:
        """Intercept an outgoing LLM API request.

        Replaces the full tools[] array with eager tools + meta-tools.
        Injects system prompt fragment.

        Args:
            body: The request body (Anthropic or OpenAI format).

        Returns:
            Modified request body.
        """
        if not self._config.enabled:
            return body

        tools = body.get("tools")
        if not tools or not isinstance(tools, list):
            return body

        # Register tools and process
        self._engine.register_tools(tools)
        result = self._engine.process()
        self._last_result = result

        # If no deferred tools, pass through
        if result.deferred_count == 0:
            return body

        # Replace tools array
        body = dict(body)  # shallow copy
        body["tools"] = result.tools_for_llm

        # Inject system prompt
        if self._config.inject_system_prompt and result.system_prompt_fragment:
            body = self._inject_system_prompt(body, result.system_prompt_fragment)

        logger.info(
            "Progressive disclosure applied: %d eager + %d deferred "
            "(%.1f%% savings)",
            result.eager_count,
            result.deferred_count,
            result.savings_pct,
        )

        return body

    def intercept_tool_call(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Intercept a tool call from the LLM response.

        If it's copium_find_tool or copium_call_tool, handle it.
        Otherwise returns None (not our tool).

        Args:
            tool_name: Name of the tool being called.
            arguments: Arguments passed to the tool.

        Returns:
            Response dict if handled, None if not a meta-tool call.
        """
        if tool_name == "copium_find_tool":
            result = self._engine.handle_find_tool(arguments)
            response_text = self._engine.format_find_tool_response(result)
            return {"type": "text", "text": response_text}

        if tool_name == "copium_call_tool":
            result = self._engine.handle_call_tool(arguments)
            if result.error:
                return {"type": "text", "text": f"Error: {result.error}"}
            # Return the original definition for the proxy to dispatch
            return {
                "type": "dispatch",
                "tool_name": result.tool_name,
                "arguments": result.arguments,
                "original_definition": result.original_definition,
            }

        return None

    def _inject_system_prompt(
        self, body: dict[str, Any], fragment: str
    ) -> dict[str, Any]:
        """Inject progressive disclosure prompt into system message."""
        # Anthropic format
        if "system" in body:
            system = body.get("system", "")
            if isinstance(system, str):
                body["system"] = system + "\n\n" + fragment
            elif isinstance(system, list):
                # System is a list of content blocks
                body["system"] = list(system) + [{"type": "text", "text": fragment}]
            return body

        # OpenAI format: prepend to messages
        messages = body.get("messages", [])
        if messages and isinstance(messages, list):
            if messages[0].get("role") == "system":
                messages = list(messages)
                messages[0] = dict(messages[0])
                content = messages[0].get("content", "")
                messages[0]["content"] = content + "\n\n" + fragment
                body["messages"] = messages
            else:
                messages = [{"role": "system", "content": fragment}] + list(messages)
                body["messages"] = messages

        return body

    def get_metrics(self) -> dict[str, Any]:
        """Return current disclosure metrics."""
        if self._last_result is None:
            return {"active": False}

        return {
            "active": True,
            "total_tools": self._last_result.total_tools,
            "eager_count": self._last_result.eager_count,
            "deferred_count": self._last_result.deferred_count,
            "original_tokens": self._last_result.original_tokens,
            "disclosed_tokens": self._last_result.disclosed_tokens,
            "savings_pct": round(self._last_result.savings_pct, 1),
        }
