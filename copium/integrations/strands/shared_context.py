"""Strands shared context integration for multi-agent workflows.

Provides CopiumStrandsContext for shared context in Strands agents.

Usage:

    from copium.integrations.strands.shared_context import CopiumStrandsContext

    ctx = CopiumStrandsContext(persistent=True)

    # In agent A's tool
    ctx.store("analysis", analysis_result, agent="analyzer")

    # In agent B's tool
    analysis = ctx.retrieve("analysis")
"""

from __future__ import annotations

import logging
from typing import Any

from copium import SharedContext

logger = logging.getLogger(__name__)


class CopiumStrandsContext:
    """Shared context wrapper for Strands multi-agent workflows.

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
            content: Content to compress.
            agent: Agent name.
            confidence: Confidence score.

        Returns:
            Compression stats.
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
            key: Context key.
            full: Return uncompressed original.

        Returns:
            Content or None.
        """
        return self._ctx.get(key, full=full)

    def keys(self) -> list[str]:
        """List available context keys."""
        return self._ctx.keys()

    @property
    def stats(self) -> Any:
        """Compression statistics."""
        return self._ctx.stats()
