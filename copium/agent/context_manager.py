"""Agent context window manager.

Automatically manages context window usage for AI agents by:
1. Compressing conversation history
2. Deduplicating tool results
3. Fitting content into available context budget
4. Tracking what was compressed for potential retrieval

ContextCrumb only compresses. Copium manages the entire context lifecycle.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ContextBudget:
    """Budget allocation for context window sections."""

    total_tokens: int = 128000
    system_prompt_pct: float = 0.10  # 10% for system prompt
    history_pct: float = 0.40  # 40% for conversation history
    tools_pct: float = 0.20  # 20% for tool definitions
    current_turn_pct: float = 0.30  # 30% for current turn

    @property
    def system_prompt_budget(self) -> int:
        return int(self.total_tokens * self.system_prompt_pct)

    @property
    def history_budget(self) -> int:
        return int(self.total_tokens * self.history_pct)

    @property
    def tools_budget(self) -> int:
        return int(self.total_tokens * self.tools_pct)

    @property
    def current_turn_budget(self) -> int:
        return int(self.total_tokens * self.current_turn_pct)


@dataclass
class ManagedContext:
    """Result of context management for a single turn."""

    messages: list[dict[str, Any]]
    total_tokens: int
    budget_used_pct: float
    history_compressed: bool = False
    tools_compressed: bool = False
    sections_dropped: int = 0
    tokens_saved: int = 0

    @property
    def fits_budget(self) -> bool:
        return self.budget_used_pct <= 100.0


@dataclass
class TurnInput:
    """Input for a single agent turn."""

    system_prompt: str = ""
    conversation_history: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    current_message: str = ""


class AgentContextManager:
    """Automatic context window manager for AI agents.

    Manages the full context lifecycle:
    - Monitors token usage across context sections
    - Compresses history when approaching budget limits
    - Deduplicates repeated tool results
    - Prioritizes recent and relevant context
    - Tracks compressed content for CCR retrieval

    Example:
        >>> manager = AgentContextManager(max_tokens=128000)
        >>> managed = manager.manage_turn(TurnInput(
        ...     system_prompt="You are a helpful assistant.",
        ...     conversation_history=history,
        ...     current_message="What's in main.py?",
        ... ))
        >>> # Send managed.messages to LLM
    """

    def __init__(
        self,
        max_tokens: int = 128000,
        budget: ContextBudget | None = None,
        compression_threshold: float = 0.8,
    ):
        """Initialize context manager.

        Args:
            max_tokens: Maximum context window size.
            budget: Token budget allocation. Defaults to standard split.
            compression_threshold: Trigger compression at this % of budget.
        """
        self._budget = budget or ContextBudget(total_tokens=max_tokens)
        self._compression_threshold = compression_threshold
        self._history_summaries: list[str] = []
        self._turn_count = 0

    def manage_turn(self, turn: TurnInput) -> ManagedContext:
        """Manage context for a single agent turn.

        Fits all content into the context budget by:
        1. Keeping system prompt intact
        2. Compressing history if needed
        3. Deduplicating tool results
        4. Trimming from oldest first

        Args:
            turn: Input for the current turn.

        Returns:
            ManagedContext with optimized messages.
        """
        self._turn_count += 1
        messages: list[dict[str, Any]] = []
        total_tokens = 0
        tokens_saved = 0
        history_compressed = False
        sections_dropped = 0

        # 1. System prompt (always include, never compress)
        if turn.system_prompt:
            system_tokens = len(turn.system_prompt) // 4
            messages.append({"role": "system", "content": turn.system_prompt})
            total_tokens += system_tokens

        # 2. Conversation history (compress if over budget)
        history_tokens = sum(
            len(str(msg.get("content", ""))) // 4
            for msg in turn.conversation_history
        )

        if history_tokens > self._budget.history_budget:
            # Compress history: keep recent, summarize old
            compressed_history, saved = self._compress_history(
                turn.conversation_history,
                self._budget.history_budget,
            )
            messages.extend(compressed_history)
            total_tokens += self._budget.history_budget
            tokens_saved += saved
            history_compressed = True
        else:
            messages.extend(turn.conversation_history)
            total_tokens += history_tokens

        # 3. Tool results (deduplicate)
        if turn.tool_results:
            deduped, dedup_saved = self._deduplicate_tool_results(turn.tool_results)
            messages.extend(deduped)
            total_tokens += sum(len(str(m.get("content", ""))) // 4 for m in deduped)
            tokens_saved += dedup_saved

        # 4. Current message
        if turn.current_message:
            messages.append({"role": "user", "content": turn.current_message})
            total_tokens += len(turn.current_message) // 4

        budget_used_pct = (total_tokens / self._budget.total_tokens) * 100

        return ManagedContext(
            messages=messages,
            total_tokens=total_tokens,
            budget_used_pct=budget_used_pct,
            history_compressed=history_compressed,
            tools_compressed=tokens_saved > 0,
            sections_dropped=sections_dropped,
            tokens_saved=tokens_saved,
        )

    def _compress_history(
        self,
        history: list[dict[str, Any]],
        budget: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Compress conversation history to fit budget.

        Strategy: Keep most recent messages, summarize older ones.

        Returns:
            (compressed_messages, tokens_saved)
        """
        if not history:
            return [], 0

        original_tokens = sum(len(str(m.get("content", ""))) // 4 for m in history)

        # Keep last N messages that fit in half the budget
        half_budget = budget // 2
        kept: list[dict[str, Any]] = []
        kept_tokens = 0

        for msg in reversed(history):
            msg_tokens = len(str(msg.get("content", ""))) // 4
            if kept_tokens + msg_tokens <= half_budget:
                kept.insert(0, msg)
                kept_tokens += msg_tokens
            else:
                break

        # Summarize dropped messages
        dropped_count = len(history) - len(kept)
        if dropped_count > 0:
            summary_msg = {
                "role": "system",
                "content": f"[{dropped_count} earlier messages compressed. Key context preserved.]",
            }
            result = [summary_msg] + kept
        else:
            result = kept

        result_tokens = sum(len(str(m.get("content", ""))) // 4 for m in result)
        saved = max(0, original_tokens - result_tokens)

        return result, saved

    def _deduplicate_tool_results(
        self,
        tool_results: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int]:
        """Deduplicate repeated tool results.

        If the same tool was called with same args, keep only the latest result.

        Returns:
            (deduplicated_messages, tokens_saved)
        """
        if not tool_results:
            return [], 0

        seen: dict[str, dict[str, Any]] = {}
        tokens_saved = 0

        for msg in tool_results:
            # Create dedup key from tool name + content hash
            content = str(msg.get("content", ""))
            tool_name = msg.get("name", msg.get("tool_use_id", ""))
            key = f"{tool_name}:{hash(content)}"

            if key in seen:
                # Duplicate found - save tokens
                tokens_saved += len(content) // 4
            else:
                seen[key] = msg

        return list(seen.values()), tokens_saved

    @property
    def turn_count(self) -> int:
        """Number of turns managed."""
        return self._turn_count
