"""OpenCode session adapter.

Parses OpenCode (Go-based AI coding agent) session files typically
stored in ~/.opencode/sessions/ as JSON files.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..archive import SessionMessage

logger = logging.getLogger(__name__)


class OpenCodeAdapter:
    """Parse OpenCode session JSON files."""

    name = "opencode"

    def detect(self, path: Path) -> bool:
        """Detect OpenCode session format.

        OpenCode stores sessions as JSON with a "session" top-level key
        containing messages and metadata, or in a directory with session ID names.
        """
        if path.suffix != ".json":
            return False

        # Check if path contains "opencode"
        if "opencode" in str(path).lower():
            return True

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                return False

            # OpenCode-specific structure
            if "session" in data or "provider" in data:
                session = data.get("session", data)
                if isinstance(session, dict) and "messages" in session:
                    return True

        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return False
        return False

    def parse(self, path: Path) -> list[SessionMessage]:
        """Parse OpenCode session JSON into unified messages."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        messages: list[SessionMessage] = []
        turn_index = 0

        # Navigate to messages array
        session = data.get("session", data)
        if isinstance(session, dict):
            raw_messages = session.get("messages", [])
        else:
            raw_messages = []

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

        logger.info("OpenCode adapter: parsed %d messages from %s", len(messages), path)
        return messages

    def write(self, messages: list[SessionMessage], path: Path) -> None:
        """Write messages in OpenCode session JSON format."""
        records = []
        for msg in messages:
            record: dict[str, Any] = {
                "role": msg.role,
                "content": msg.content,
            }
            if msg.metadata.get("model"):
                record["model"] = msg.metadata["model"]
            if msg.metadata.get("tool_calls"):
                record["tool_calls"] = msg.metadata["tool_calls"]
            records.append(record)

        output = {
            "session": {
                "messages": records,
            },
            "provider": "copium_export",
        }
        path.write_text(json.dumps(output, indent=2), encoding="utf-8")

    def _parse_message(self, raw: dict[str, Any], turn_index: int) -> SessionMessage | None:
        """Parse a single OpenCode message."""
        role = raw.get("role", "")
        if not role:
            return None

        content = raw.get("content", "")
        if isinstance(content, list):
            # Multi-part content
            parts = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        parts.append(part.get("text", ""))
                    elif part.get("type") == "tool_result":
                        parts.append(part.get("content", ""))
                elif isinstance(part, str):
                    parts.append(part)
            content = "\n".join(parts)
        elif not isinstance(content, str):
            content = str(content) if content else ""

        if not content:
            # Check for tool_calls (assistant messages with no text)
            tool_calls = raw.get("tool_calls", [])
            if tool_calls:
                parts = []
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        fn = tc.get("function", {})
                        name = fn.get("name", "unknown")
                        args = fn.get("arguments", "{}")
                        parts.append(f"[Tool call: {name}({args[:200]})]")
                content = "\n".join(parts)

        if not content:
            return None

        msg_type = role
        if role == "tool":
            msg_type = "tool_result"

        metadata: dict[str, Any] = {}
        if "model" in raw:
            metadata["model"] = raw["model"]
        if "tool_call_id" in raw:
            metadata["tool_call_id"] = raw["tool_call_id"]
        if "tool_calls" in raw:
            metadata["tool_calls"] = raw["tool_calls"]

        return SessionMessage(
            type=msg_type,
            role=role,
            content=content,
            metadata=metadata,
            turn_index=turn_index,
        )
