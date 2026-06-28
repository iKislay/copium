"""Cursor conversation JSON session adapter.

Parses Cursor's conversation JSON files typically stored in
~/.cursor/conversations/ or workspace-local .cursor/ directories.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..archive import SessionMessage

logger = logging.getLogger(__name__)


class CursorAdapter:
    """Parse Cursor conversation JSON sessions."""

    name = "cursor"

    def detect(self, path: Path) -> bool:
        """Detect Cursor conversation format.

        Cursor stores conversations as JSON with a specific structure
        containing "messages" array with role/content pairs and
        optional "workspace" or "composerId" fields.
        """
        if path.suffix != ".json":
            return False

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                return False

            # Cursor-specific fields
            if "composerId" in data or "workspaceId" in data:
                return True

            # Check for messages array with Cursor's structure
            messages = data.get("messages", data.get("conversation", []))
            if isinstance(messages, list) and len(messages) > 0:
                first = messages[0]
                if isinstance(first, dict) and "role" in first:
                    # Cursor often includes "type" or "context" fields
                    if "context" in first or "type" in data:
                        return True

        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return False
        return False

    def parse(self, path: Path) -> list[SessionMessage]:
        """Parse Cursor conversation JSON into unified messages."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        messages: list[SessionMessage] = []
        turn_index = 0

        # Extract the messages array
        raw_messages = data.get("messages", data.get("conversation", []))
        if not isinstance(raw_messages, list):
            return messages

        for raw_msg in raw_messages:
            if not isinstance(raw_msg, dict):
                continue

            msg = self._parse_message(raw_msg, turn_index)
            if msg:
                messages.append(msg)
                if msg.role in ("user", "assistant"):
                    turn_index += 1

        logger.info("Cursor adapter: parsed %d messages from %s", len(messages), path)
        return messages

    def write(self, messages: list[SessionMessage], path: Path) -> None:
        """Write messages in Cursor conversation JSON format."""
        records = []
        for msg in messages:
            record: dict[str, Any] = {
                "role": msg.role,
                "content": msg.content,
            }
            if msg.metadata.get("model"):
                record["model"] = msg.metadata["model"]
            if msg.metadata.get("context"):
                record["context"] = msg.metadata["context"]
            records.append(record)

        output = {"messages": records, "type": "cursor_conversation"}
        path.write_text(json.dumps(output, indent=2), encoding="utf-8")

    def _parse_message(self, raw: dict[str, Any], turn_index: int) -> SessionMessage | None:
        """Parse a single Cursor message."""
        role = raw.get("role", "")
        if not role:
            return None

        # Extract content — Cursor can have string or structured content
        content = raw.get("content", "")
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        parts.append(part.get("text", ""))
                    elif part.get("type") == "code":
                        parts.append(f"```\n{part.get('text', '')}\n```")
                elif isinstance(part, str):
                    parts.append(part)
            content = "\n".join(parts)
        elif not isinstance(content, str):
            content = str(content) if content else ""

        if not content:
            return None

        # Map Cursor roles to standard roles
        msg_type = role
        if role == "function":
            role = "tool"
            msg_type = "tool_result"

        metadata: dict[str, Any] = {}
        if "model" in raw:
            metadata["model"] = raw["model"]
        if "context" in raw:
            metadata["context"] = raw["context"]
        if "timestamp" in raw:
            metadata["timestamp"] = raw["timestamp"]

        return SessionMessage(
            type=msg_type,
            role=role,
            content=content,
            metadata=metadata,
            turn_index=turn_index,
        )
