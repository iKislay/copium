"""LangGraph shared context integration for multi-agent workflows.

Provides LangGraph nodes and state helpers for SharedContext:
- create_shared_context_node: Node factory for shared context operations
- CopiumSharedContext: SharedContext wrapper for LangGraph state

Usage in LangGraph:

    from copium.integrations.langchain.shared_context import (
        CopiumSharedContext,
        create_shared_context_store_node,
        create_shared_context_retrieve_node,
    )

    ctx = CopiumSharedContext(persistent=True)

    def researcher_node(state):
        result = do_research()
        ctx.store("research", result, agent="researcher")
        return {"messages": [result]}

    def coder_node(state):
        research = ctx.retrieve("research")
        code = write_code(research)
        return {"messages": [code]}
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from copium import SharedContext

logger = logging.getLogger(__name__)


class CopiumSharedContext:
    """SharedContext wrapper designed for LangGraph multi-agent state.

    Provides a clean API for storing and retrieving compressed context
    within LangGraph node functions.

    Args:
        persistent: Enable persistent storage.
        model: Model for compression pipeline.
        project_id: Project scope.
    """

    def __init__(
        self,
        *,
        persistent: bool = True,
        model: str = "claude-sonnet-4-5-20250929",
        project_id: str | None = None,
    ) -> None:
        self._ctx = SharedContext(
            model=model,
            persistent=persistent,
            project_id=project_id,
        )

    def store(
        self,
        key: str,
        content: str,
        *,
        agent: str | None = None,
        confidence: float = 0.9,
    ) -> dict[str, Any]:
        """Store content in shared context.

        Args:
            key: Context key.
            content: Content to compress and store.
            agent: Agent name for provenance.
            confidence: Confidence score.

        Returns:
            Dict with compression stats.
        """
        entry = self._ctx.put(key, content, agent=agent, confidence=confidence)
        return {
            "key": key,
            "original_tokens": entry.original_tokens,
            "compressed_tokens": entry.compressed_tokens,
            "savings_percent": entry.savings_percent,
        }

    def retrieve(self, key: str, *, full: bool = False) -> str | None:
        """Retrieve compressed context.

        Args:
            key: Context key to retrieve.
            full: If True, return uncompressed original.

        Returns:
            Content or None.
        """
        return self._ctx.get(key, full=full)

    def keys(self) -> list[str]:
        """List all available context keys."""
        return self._ctx.keys()

    def search(self, query: str, *, top_k: int = 5) -> list:
        """Semantic search over shared context."""
        return self._ctx.search(query, top_k=top_k)

    @property
    def stats(self) -> Any:
        """Get compression statistics."""
        return self._ctx.stats()


def create_shared_context_store_node(
    ctx: CopiumSharedContext,
    key: str,
    *,
    agent: str | None = None,
    content_extractor: Callable[[dict], str] | None = None,
) -> Callable:
    """Create a LangGraph node that stores content in shared context.

    Args:
        ctx: CopiumSharedContext instance.
        key: Key to store content under.
        agent: Agent name for provenance.
        content_extractor: Function to extract content from state.
            Defaults to extracting last message content.

    Returns:
        A LangGraph-compatible node function.
    """

    def node(state: dict) -> dict:
        if content_extractor:
            content = content_extractor(state)
        else:
            # Default: extract last message content
            messages = state.get("messages", [])
            if messages:
                last_msg = messages[-1]
                content = (
                    last_msg.content
                    if hasattr(last_msg, "content")
                    else str(last_msg)
                )
            else:
                return state

        stats = ctx.store(key, content, agent=agent)
        logger.debug("SharedContext store node: %s", stats)
        return state

    return node


def create_shared_context_retrieve_node(
    ctx: CopiumSharedContext,
    key: str,
    *,
    state_key: str = "shared_context",
    full: bool = False,
) -> Callable:
    """Create a LangGraph node that retrieves content from shared context.

    Args:
        ctx: CopiumSharedContext instance.
        key: Key to retrieve.
        state_key: State dict key to store retrieved content.
        full: If True, retrieve uncompressed original.

    Returns:
        A LangGraph-compatible node function.
    """

    def node(state: dict) -> dict:
        content = ctx.retrieve(key, full=full)
        if content:
            return {state_key: {key: content}}
        return state

    return node
