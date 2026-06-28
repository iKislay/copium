"""Claude Code JSONL session adapter.

Parses Claude Code session archives stored as JSONL files in
~/.claude/projects/<project>/sessions/<session-id>.jsonl
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..archive import SessionMessage

logger = logging.getLogger(__name__)


class ClaudeCodeAdapter:
    """Parse Claude Code JSONL sessions."""

    name = "claude_code"

    def detect(self, path: Path) -> bool:
        """Detect Claude Code JSONL format.

        Claude Code sessions are JSONL files typically under ~/.claude/
        with lines containing {"type": "human"|"assistant"|"tool_use"|"tool_result"}.
        """
        if path.suffix != ".jsonl":
            return False

        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    # Claude Code format has "type" field with specific values
                    if data.get("type") in ("human", "assistant", "tool_use", "tool_result"):
                        return True
                    # Also check for message.role pattern
                    msg = data.get("message", {})
                    if isinstance(msg, dict) and msg.get("role") in ("user", "assistant"):
                        return True
                    break  # Only check first meaningful line
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return False
        return False

    def parse(self, path: Path) -> list[SessionMessage]:
        """Parse Claude Code JSONL session into unified messages."""
        messages: list[SessionMessage] = []
        turn_index = 0

        with open(path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(
                        "Skipping invalid JSON at line %d in %s", line_num, path
                    )
                    continue

                msg = self._parse_record(data, turn_index)
                if msg:
                    messages.append(msg)
                    if msg.type in ("human", "assistant"):
                        turn_index += 1

        logger.info("Claude Code adapter: parsed %d messages from %s", len(messages), path)
        return messages

    def write(self, messages: list[SessionMessage], path: Path) -> None:
        """Write messages back in Claude Code JSONL format."""
        with open(path, "w", encoding="utf-8") as f:
            for msg in messages:
                record = self._to_record(msg)
                f.write(json.dumps(record) + "\n")

    def _parse_record(self, data: dict[str, Any], turn_index: int) -> SessionMessage | None:
        """Parse a single JSONL record."""
        # Skip metadata records
        if "_copium_compacted" in data:
            return None

        msg_type = data.get("type", "")
        message_data = data.get("message", data)

        # Extract content
        content = self._extract_content(message_data)

        # Determine role
        role = message_data.get("role", "")
        if not role:
            if msg_type == "human":
                role = "user"
            elif msg_type == "assistant":
                role = "assistant"
            elif msg_type in ("tool_use", "tool_result"):
                role = "tool"

        # Extract metadata
        metadata: dict[str, Any] = {}
        if "model" in message_data:
            metadata["model"] = message_data["model"]
        if "tool" in data:
            metadata["tool"] = data["tool"]
        if "timestamp" in data:
            metadata["timestamp"] = data["timestamp"]
        if msg_type == "tool_use" and "tool" in data:
            tool_info = data["tool"]
            if isinstance(tool_info, dict):
                metadata["tool_name"] = tool_info.get("name", "")
                metadata["tool_input"] = tool_info.get("input", {})

        return SessionMessage(
            type=msg_type or role,
            role=role,
            content=content,
            metadata=metadata,
            turn_index=turn_index,
        )

    def _extract_content(self, message_data: dict[str, Any]) -> str:
        """Extract text content from message data."""
        content_raw = message_data.get("content", "")

        if isinstance(content_raw, str):
            return content_raw

        if isinstance(content_raw, list):
            parts = []
            for part in content_raw:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        parts.append(part.get("text", ""))
                    elif part.get("type") == "tool_result":
                        parts.append(part.get("content", ""))
                    elif part.get("type") == "tool_use":
                        # Include tool use info
                        name = part.get("name", "unknown")
                        inp = part.get("input", {})
                        parts.append(f"[Tool: {name}({json.dumps(inp, default=str)[:200]})]")
                elif isinstance(part, str):
                    parts.append(part)
            return "\n".join(parts)

        return str(content_raw) if content_raw else ""

    def _to_record(self, msg: SessionMessage) -> dict[str, Any]:
        """Convert a SessionMessage to Claude Code JSONL record."""
        record: dict[str, Any] = {
            "type": msg.type,
            "message": {
                "role": msg.role,
                "content": msg.content,
            },
        }

        if "model" in msg.metadata:
            record["message"]["model"] = msg.metadata["model"]
        if "tool" in msg.metadata:
            record["tool"] = msg.metadata["tool"]
        if "timestamp" in msg.metadata:
            record["timestamp"] = msg.metadata["timestamp"]

        return record
