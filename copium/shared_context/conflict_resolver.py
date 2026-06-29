"""Conflict resolution strategies for SharedContext.

When multiple agents write to the same key, a conflict resolution
strategy determines which version wins or how to merge them.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Callable

from copium.shared_context.provenance import AgentIdentity

logger = logging.getLogger(__name__)


class ConflictStrategy(Enum):
    """Available conflict resolution strategies."""

    LAST_WRITE_WINS = "last_write"  # Most recent update wins (default)
    HIGHEST_CONFIDENCE = "confidence"  # Highest confidence score wins
    AGENT_PRIORITY = "agent_priority"  # Predefined agent hierarchy
    MERGE = "merge"  # LLM-mediated merge
    KEEP_BOTH = "keep_both"  # Keep both, flag as conflicting


class ConflictResult:
    """Result of a conflict resolution."""

    def __init__(
        self,
        winner: str,
        content: str,
        strategy_used: ConflictStrategy,
        *,
        merged: bool = False,
        kept_entries: list[str] | None = None,
    ) -> None:
        self.winner = winner  # ID of winning entry
        self.content = content  # Resolved content
        self.strategy_used = strategy_used
        self.merged = merged
        self.kept_entries = kept_entries or []


class ConflictResolver:
    """Resolves write conflicts when multiple agents write to the same key.

    Args:
        strategy: Default conflict resolution strategy.
        agent_priority: Ordered list of agent names (first = highest priority).
            Used only with AGENT_PRIORITY strategy.
        merge_fn: Custom merge function for MERGE strategy. Takes two content
            strings and returns the merged result. If not provided, defaults
            to concatenation with delineation.
    """

    def __init__(
        self,
        strategy: ConflictStrategy = ConflictStrategy.LAST_WRITE_WINS,
        agent_priority: list[str] | None = None,
        merge_fn: Callable[[str, str], str] | None = None,
    ) -> None:
        self._strategy = strategy
        self._agent_priority = agent_priority or []
        self._merge_fn = merge_fn

    @property
    def strategy(self) -> ConflictStrategy:
        return self._strategy

    def resolve(
        self,
        existing_content: str,
        existing_agent: AgentIdentity | None,
        existing_confidence: float,
        existing_id: str,
        new_content: str,
        new_agent: AgentIdentity | None,
        new_confidence: float,
        new_id: str,
        *,
        strategy_override: ConflictStrategy | None = None,
    ) -> ConflictResult:
        """Resolve a conflict between existing and new content.

        Args:
            existing_content: Currently stored content.
            existing_agent: Agent that wrote existing content.
            existing_confidence: Confidence of existing content.
            existing_id: ID of existing entry.
            new_content: New content being written.
            new_agent: Agent writing new content.
            new_confidence: Confidence of new content.
            new_id: ID of new entry.
            strategy_override: Override the default strategy for this resolution.

        Returns:
            ConflictResult indicating what won and the resolved content.
        """
        strategy = strategy_override or self._strategy

        if strategy == ConflictStrategy.LAST_WRITE_WINS:
            return self._resolve_last_write(new_content, new_id)

        elif strategy == ConflictStrategy.HIGHEST_CONFIDENCE:
            return self._resolve_confidence(
                existing_content, existing_confidence, existing_id,
                new_content, new_confidence, new_id,
            )

        elif strategy == ConflictStrategy.AGENT_PRIORITY:
            return self._resolve_agent_priority(
                existing_content, existing_agent, existing_id,
                new_content, new_agent, new_id,
            )

        elif strategy == ConflictStrategy.MERGE:
            return self._resolve_merge(
                existing_content, existing_id,
                new_content, new_id,
            )

        elif strategy == ConflictStrategy.KEEP_BOTH:
            return self._resolve_keep_both(
                existing_content, existing_id,
                new_content, new_id,
            )

        # Fallback: last write wins
        return self._resolve_last_write(new_content, new_id)

    def _resolve_last_write(
        self, new_content: str, new_id: str
    ) -> ConflictResult:
        """Most recent write wins."""
        return ConflictResult(
            winner=new_id,
            content=new_content,
            strategy_used=ConflictStrategy.LAST_WRITE_WINS,
        )

    def _resolve_confidence(
        self,
        existing_content: str,
        existing_confidence: float,
        existing_id: str,
        new_content: str,
        new_confidence: float,
        new_id: str,
    ) -> ConflictResult:
        """Highest confidence wins."""
        if new_confidence >= existing_confidence:
            return ConflictResult(
                winner=new_id,
                content=new_content,
                strategy_used=ConflictStrategy.HIGHEST_CONFIDENCE,
            )
        return ConflictResult(
            winner=existing_id,
            content=existing_content,
            strategy_used=ConflictStrategy.HIGHEST_CONFIDENCE,
        )

    def _resolve_agent_priority(
        self,
        existing_content: str,
        existing_agent: AgentIdentity | None,
        existing_id: str,
        new_content: str,
        new_agent: AgentIdentity | None,
        new_id: str,
    ) -> ConflictResult:
        """Agent priority hierarchy determines winner."""
        existing_name = existing_agent.agent_name if existing_agent else ""
        new_name = new_agent.agent_name if new_agent else ""

        existing_rank = (
            self._agent_priority.index(existing_name)
            if existing_name in self._agent_priority
            else len(self._agent_priority)
        )
        new_rank = (
            self._agent_priority.index(new_name)
            if new_name in self._agent_priority
            else len(self._agent_priority)
        )

        # Lower index = higher priority
        if new_rank <= existing_rank:
            return ConflictResult(
                winner=new_id,
                content=new_content,
                strategy_used=ConflictStrategy.AGENT_PRIORITY,
            )
        return ConflictResult(
            winner=existing_id,
            content=existing_content,
            strategy_used=ConflictStrategy.AGENT_PRIORITY,
        )

    def _resolve_merge(
        self,
        existing_content: str,
        existing_id: str,
        new_content: str,
        new_id: str,
    ) -> ConflictResult:
        """Merge contents using the configured merge function."""
        if self._merge_fn:
            merged = self._merge_fn(existing_content, new_content)
        else:
            # Default: concatenate with separator
            merged = (
                f"[Previous (from {existing_id})]:\n{existing_content}\n\n"
                f"[Update (from {new_id})]:\n{new_content}"
            )

        return ConflictResult(
            winner=new_id,
            content=merged,
            strategy_used=ConflictStrategy.MERGE,
            merged=True,
        )

    def _resolve_keep_both(
        self,
        existing_content: str,
        existing_id: str,
        new_content: str,
        new_id: str,
    ) -> ConflictResult:
        """Keep both entries (caller should store both)."""
        return ConflictResult(
            winner=new_id,
            content=new_content,
            strategy_used=ConflictStrategy.KEEP_BOTH,
            kept_entries=[existing_id, new_id],
        )
