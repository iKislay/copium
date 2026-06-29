"""Agno shared context integration for multi-agent teams.

Provides CopiumAgnoTeam wrapper that enables automatic context
sharing between Agno agents in a team.

Usage:

    from copium.integrations.agno.shared_context import CopiumAgnoTeam
    from agno.agent import Agent

    researcher = Agent(model=model, ...)
    coder = Agent(model=model, ...)

    team = CopiumAgnoTeam(
        agents=[researcher, coder],
        persistent=True,
    )
    # Context from researcher is compressed and available to coder
"""

from __future__ import annotations

import logging
from typing import Any

from copium import SharedContext

logger = logging.getLogger(__name__)


class CopiumAgnoTeam:
    """Shared context wrapper for Agno multi-agent teams.

    Manages compressed context sharing between agents in a team.

    Args:
        agents: List of agent names or identifiers.
        persistent: Enable persistent storage.
        model: Model for compression pipeline.
        project_id: Project scope.
    """

    def __init__(
        self,
        *,
        agents: list[str] | None = None,
        persistent: bool = True,
        model: str = "claude-sonnet-4-5-20250929",
        project_id: str | None = None,
    ) -> None:
        self._agents = agents or []
        self._ctx = SharedContext(
            model=model,
            persistent=persistent,
            project_id=project_id,
        )

    def store_output(
        self,
        agent_name: str,
        output: str,
        *,
        key: str | None = None,
        confidence: float = 0.9,
    ) -> dict[str, Any]:
        """Store an agent's output in shared context.

        Args:
            agent_name: Name of the agent.
            output: Agent output to compress.
            key: Custom key (defaults to agent_name).
            confidence: Confidence score.

        Returns:
            Compression stats dict.
        """
        context_key = key or agent_name
        entry = self._ctx.put(
            context_key, output, agent=agent_name, confidence=confidence
        )
        return {
            "key": context_key,
            "agent": agent_name,
            "original_tokens": entry.original_tokens,
            "compressed_tokens": entry.compressed_tokens,
            "savings_percent": entry.savings_percent,
        }

    def get_context_for(
        self,
        agent_name: str,
        *,
        exclude_self: bool = True,
        full: bool = False,
    ) -> dict[str, str]:
        """Get all available shared context for an agent.

        Args:
            agent_name: The agent requesting context.
            exclude_self: Exclude the agent's own output.
            full: Return uncompressed originals.

        Returns:
            Dict of key → compressed content.
        """
        result = {}
        for key in self._ctx.keys():
            if exclude_self and key == agent_name:
                continue
            content = self._ctx.get(key, full=full)
            if content:
                result[key] = content
        return result

    def get(self, key: str, *, full: bool = False) -> str | None:
        """Direct context retrieval by key."""
        return self._ctx.get(key, full=full)

    @property
    def stats(self) -> Any:
        """Compression statistics."""
        return self._ctx.stats()
