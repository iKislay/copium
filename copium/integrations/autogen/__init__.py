"""AutoGen integration for Copium SharedContext.

Provides middleware that intercepts AutoGen messages between agents
and automatically compresses/stores context in SharedContext.

Usage:

    from copium.integrations.autogen import SharedContextMiddleware

    ctx_middleware = SharedContextMiddleware(persistent=True)

    # Hook into agent message flow
    researcher = AssistantAgent(name="researcher", ...)
    coder = AssistantAgent(name="coder", ...)

    # Capture researcher output
    ctx_middleware.on_message("researcher", researcher_output)

    # Inject compressed context for coder
    enriched = ctx_middleware.enrich_message("coder", original_message)
"""

from __future__ import annotations

import logging
from typing import Any

from copium import SharedContext

logger = logging.getLogger(__name__)


class SharedContextMiddleware:
    """Message middleware for AutoGen multi-agent conversations.

    Intercepts messages between AutoGen agents to:
    1. Store agent outputs in SharedContext (compressed)
    2. Inject compressed context from other agents into messages

    Args:
        persistent: Enable persistent storage.
        model: Model for compression pipeline.
        inject_context: Whether to auto-inject context into messages.
        project_id: Project scope for isolation.
    """

    def __init__(
        self,
        *,
        persistent: bool = True,
        model: str = "claude-sonnet-4-5-20250929",
        inject_context: bool = True,
        project_id: str | None = None,
    ) -> None:
        self._ctx = SharedContext(
            model=model,
            persistent=persistent,
            project_id=project_id,
        )
        self._inject_context = inject_context

    def on_message(
        self,
        sender_name: str,
        message: str,
        *,
        confidence: float = 0.9,
    ) -> dict[str, Any]:
        """Called when an agent sends a message. Stores in shared context.

        Args:
            sender_name: Name of the sending agent.
            message: Message content to store.
            confidence: Confidence score.

        Returns:
            Dict with compression stats.
        """
        key = f"{sender_name}_output"
        entry = self._ctx.put(key, message, agent=sender_name, confidence=confidence)
        logger.debug(
            "AutoGen middleware: stored %s output (%d → %d tokens)",
            sender_name, entry.original_tokens, entry.compressed_tokens,
        )
        return {
            "key": key,
            "original_tokens": entry.original_tokens,
            "compressed_tokens": entry.compressed_tokens,
            "savings_percent": entry.savings_percent,
        }

    def enrich_message(
        self,
        receiver_name: str,
        message: str,
        *,
        source_agents: list[str] | None = None,
    ) -> str:
        """Inject compressed context into a message for the receiving agent.

        Args:
            receiver_name: Name of the receiving agent.
            message: Original message to enrich.
            source_agents: Specific agents to get context from.
                If None, gets context from all available agents.

        Returns:
            Enriched message with shared context prefix.
        """
        if not self._inject_context:
            return message

        context_parts: list[str] = []

        if source_agents:
            for agent_name in source_agents:
                key = f"{agent_name}_output"
                content = self._ctx.get(key)
                if content:
                    context_parts.append(f"[{agent_name}]: {content}")
        else:
            for key in self._ctx.keys():
                # Don't inject the receiver's own output
                if key == f"{receiver_name}_output":
                    continue
                content = self._ctx.get(key)
                if content:
                    agent = key.replace("_output", "")
                    context_parts.append(f"[{agent}]: {content}")

        if not context_parts:
            return message

        context_block = "[Shared Context]:\n" + "\n\n".join(context_parts)
        return f"{context_block}\n\n{message}"

    def get_context(self, key: str, *, full: bool = False) -> str | None:
        """Directly retrieve context by key."""
        return self._ctx.get(key, full=full)

    @property
    def stats(self) -> Any:
        """Get compression statistics."""
        return self._ctx.stats()
