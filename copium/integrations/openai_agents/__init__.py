"""OpenAI Agents SDK integration for Copium SharedContext.

Provides handoff wrappers that compress context during agent-to-agent
handoffs in OpenAI's Agents SDK.

Usage:

    from copium.integrations.openai_agents import CopiumHandoff

    researcher = Agent(name="Researcher", ...)
    coder = Agent(name="Coder", ...)

    handoff = CopiumHandoff(persistent=True)

    # After researcher produces output
    handoff.store("research", researcher_output, agent="Researcher")

    # Before coder starts, get compressed context
    compressed = handoff.get("research")
"""

from __future__ import annotations

import logging
from typing import Any

from copium import SharedContext

logger = logging.getLogger(__name__)


class CopiumHandoff:
    """Compressed context handoff for OpenAI Agents SDK.

    Wraps SharedContext to provide a handoff-oriented API that
    compresses context between agent transitions.

    Args:
        persistent: Enable persistent storage across sessions.
        model: Model for compression pipeline.
        compression_ratio: Target compression ratio (informational).
        project_id: Project scope for isolation.
    """

    def __init__(
        self,
        *,
        persistent: bool = True,
        model: str = "claude-sonnet-4-5-20250929",
        compression_ratio: float = 0.8,
        project_id: str | None = None,
    ) -> None:
        self._ctx = SharedContext(
            model=model,
            persistent=persistent,
            project_id=project_id,
        )
        self._compression_ratio = compression_ratio

    def store(
        self,
        context_key: str,
        content: str,
        *,
        agent: str | None = None,
        confidence: float = 0.9,
    ) -> dict[str, Any]:
        """Store agent output for handoff to next agent.

        Args:
            context_key: Key for this context piece.
            content: Agent output to compress and store.
            agent: Name of the agent producing this output.
            confidence: Confidence score for conflict resolution.

        Returns:
            Dict with compression stats.
        """
        entry = self._ctx.put(
            context_key, content, agent=agent, confidence=confidence
        )
        logger.debug(
            "Handoff store(%s): %d → %d tokens",
            context_key, entry.original_tokens, entry.compressed_tokens,
        )
        return {
            "key": context_key,
            "original_tokens": entry.original_tokens,
            "compressed_tokens": entry.compressed_tokens,
            "savings_percent": entry.savings_percent,
        }

    def get(
        self,
        context_key: str,
        *,
        full: bool = False,
    ) -> str | None:
        """Get compressed context for the receiving agent.

        Args:
            context_key: Key of the stored context.
            full: If True, return uncompressed original.

        Returns:
            Compressed content, or None if not found.
        """
        return self._ctx.get(context_key, full=full)

    def handoff_context(
        self,
        from_agent: str,
        to_agent: str,
        content: str,
        context_key: str | None = None,
    ) -> str:
        """Perform a complete handoff: store from one agent, retrieve for another.

        Args:
            from_agent: Name of sending agent.
            to_agent: Name of receiving agent.
            content: Content to compress and hand off.
            context_key: Optional key (defaults to "{from_agent}_to_{to_agent}").

        Returns:
            Compressed content ready for the receiving agent.
        """
        key = context_key or f"{from_agent}_to_{to_agent}"
        self.store(key, content, agent=from_agent)
        result = self.get(key)
        logger.info(
            "Handoff %s → %s via key '%s'", from_agent, to_agent, key
        )
        return result or content  # Fallback to original if compression fails

    @property
    def stats(self) -> Any:
        """Get compression statistics."""
        return self._ctx.stats()
