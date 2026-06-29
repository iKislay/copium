"""Eager loading policy for progressive tool disclosure.

Decides which tools should be loaded eagerly (sent to LLM in full)
versus deferred (available only via copium_find_tool).
"""

from __future__ import annotations

from copium.mcp_proxy.progressive_disclosure.config import ProgressiveDisclosureConfig
from copium.mcp_proxy.progressive_disclosure.registry import ToolEntry


class EagerLoadingPolicy:
    """Classify tools as eager (sent to LLM) or deferred (behind find_tool).

    Heuristics:
    1. Tools matching eager_patterns are always eager
    2. Tools with eager_prefixes are always eager
    3. Previously-called tools in this session are eager
    4. Respects eager_load_max cap
    """

    def __init__(self, config: ProgressiveDisclosureConfig) -> None:
        self._config = config

    def classify(
        self, tools: list[ToolEntry]
    ) -> tuple[list[ToolEntry], list[ToolEntry]]:
        """Split tools into eager (sent to LLM) and deferred (behind find_tool).

        Returns:
            Tuple of (eager_tools, deferred_tools).
        """
        eager: list[ToolEntry] = []
        deferred: list[ToolEntry] = []

        for tool in tools:
            if self._should_eager_load(tool):
                eager.append(tool)
            else:
                deferred.append(tool)

        # If too many eager tools, move lowest-priority to deferred
        if len(eager) > self._config.eager_load_max:
            # Sort by priority: called tools first, then pattern matches
            eager.sort(key=self._priority_score, reverse=True)
            overflow = eager[self._config.eager_load_max:]
            eager = eager[:self._config.eager_load_max]
            deferred = overflow + deferred

        return eager, deferred

    def _should_eager_load(self, tool: ToolEntry) -> bool:
        """Determine if a tool should be loaded eagerly."""
        name = tool.name.lower()

        # Always eager: tools matching configured prefixes
        for prefix in self._config.eager_prefixes:
            if name.startswith(prefix.lower()):
                return True

        # Always eager: tools matching configured patterns
        for pattern in self._config.eager_patterns:
            if pattern.lower() in name:
                return True

        # Eager if previously called in this session
        if tool.call_count > 0:
            return True

        return False

    def _priority_score(self, tool: ToolEntry) -> float:
        """Score a tool's priority for eager loading."""
        score = 0.0

        # Previously-called tools are highest priority
        if tool.call_count > 0:
            score += 10.0 + tool.call_count

        # Prefix matches get moderate priority
        name = tool.name.lower()
        for prefix in self._config.eager_prefixes:
            if name.startswith(prefix.lower()):
                score += 5.0
                break

        # Pattern matches get base priority
        for pattern in self._config.eager_patterns:
            if pattern.lower() in name:
                score += 2.0
                break

        return score
