"""Session applicator — apply compacted sessions as context.

Converts a compacted SessionArchive into messages suitable for injection
into a new API call (Anthropic or OpenAI format).
"""

from __future__ import annotations

import logging
from typing import Any

from .archive import SessionArchive, SessionMessage

logger = logging.getLogger(__name__)


class SessionApplicator:
    """Apply a compacted session as context for a new conversation."""

    def __init__(self, *, max_context_messages: int = 0, format: str = "anthropic"):
        """Initialize applicator.

        Args:
            max_context_messages: Max messages to include (0 = all).
            format: Output format — 'anthropic' or 'openai'.
        """
        self.max_context_messages = max_context_messages
        self.format = format

    def apply(
        self, archive: SessionArchive, new_query: str | None = None
    ) -> list[dict[str, Any]]:
        """Convert compacted archive into messages for an API call.

        Args:
            archive: The (compacted) session archive to apply.
            new_query: Optional new user query to append.

        Returns:
            List of message dicts in the target format.
        """
        messages = archive.messages
        if self.max_context_messages > 0:
            messages = messages[-self.max_context_messages :]

        result: list[dict[str, Any]] = []
        for msg in messages:
            converted = self._convert_message(msg)
            if converted:
                result.append(converted)

        # Append new query if provided
        if new_query:
            if self.format == "openai":
                result.append({"role": "user", "content": new_query})
            else:
                result.append({"role": "user", "content": new_query})

        return result

    def _convert_message(self, msg: SessionMessage) -> dict[str, Any] | None:
        """Convert a SessionMessage to the target format."""
        if not msg.content.strip():
            return None

        if self.format == "openai":
            return self._to_openai(msg)
        return self._to_anthropic(msg)

    def _to_anthropic(self, msg: SessionMessage) -> dict[str, Any]:
        """Convert to Anthropic message format."""
        role = msg.role
        if role == "tool":
            # Tool results in Anthropic format
            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": msg.metadata.get("tool_use_id", "compacted"),
                        "content": msg.content,
                    }
                ],
            }
        return {"role": role, "content": msg.content}

    def _to_openai(self, msg: SessionMessage) -> dict[str, Any]:
        """Convert to OpenAI message format."""
        role = msg.role
        if role == "tool":
            return {
                "role": "tool",
                "tool_call_id": msg.metadata.get("tool_call_id", "compacted"),
                "content": msg.content,
            }
        return {"role": role, "content": msg.content}
