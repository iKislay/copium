"""Session archive parser and data model.

Parses Claude Code JSONL session files and other agent session formats
into a unified internal representation.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SessionMessage:
    """A single message in a session archive."""

    type: str  # human, assistant, tool_use, tool_result
    role: str  # user, assistant, tool
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""
    turn_index: int = 0

    def __post_init__(self) -> None:
        if not self.content_hash and self.content:
            self.content_hash = hashlib.sha256(
                self.content.encode("utf-8")
            ).hexdigest()[:16]


@dataclass
class CompactConfig:
    """Configuration for session archive compaction."""

    deduplicate_tool_outputs: bool = True
    collapse_assistant_preamble: bool = True
    remove_ansi: bool = True
    group_identical_turns: bool = True
    near_duplicate_threshold: float = 0.85
    min_content_length: int = 50  # Don't dedup tiny outputs


@dataclass
class CompactResult:
    """Result of a session archive compaction."""

    original_messages: int = 0
    compacted_messages: int = 0
    original_tokens_est: int = 0
    compacted_tokens_est: int = 0
    dedup_hits: int = 0
    near_dedup_hits: int = 0
    preamble_collapsed: int = 0
    ansi_stripped: int = 0

    @property
    def savings_pct(self) -> float:
        if self.original_tokens_est == 0:
            return 0.0
        return (
            (self.original_tokens_est - self.compacted_tokens_est)
            / self.original_tokens_est
            * 100
        )


class SessionArchive:
    """Parse and manipulate AI agent session archives.

    Supports Claude Code JSONL format natively. Other formats via adapters.
    """

    def __init__(self, path: Path | None = None, messages: list[SessionMessage] | None = None):
        self.path = path
        self.messages: list[SessionMessage] = messages or []
        self._metadata: dict[str, Any] = {}

        if path and path.exists():
            self.messages = self._parse_jsonl(path)

    @property
    def metadata(self) -> dict[str, Any]:
        return self._metadata

    @property
    def is_compacted(self) -> bool:
        return self._metadata.get("_copium_compacted", False)

    def _parse_jsonl(self, path: Path) -> list[SessionMessage]:
        """Parse a JSONL session file into typed messages."""
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
                    logger.warning("Skipping invalid JSON at line %d in %s", line_num, path)
                    continue

                msg = self._parse_message(data, turn_index)
                if msg:
                    messages.append(msg)
                    if msg.type in ("human", "assistant"):
                        turn_index += 1

        logger.info("Parsed %d messages from %s", len(messages), path)
        return messages

    def _parse_message(self, data: dict[str, Any], turn_index: int) -> SessionMessage | None:
        """Parse a single JSONL record into a SessionMessage."""
        # Check for metadata record
        if "_copium_compacted" in data:
            self._metadata.update(data)
            return None

        msg_type = data.get("type", "")
        message_data = data.get("message", data)

        # Extract content
        content = ""
        if isinstance(message_data.get("content"), str):
            content = message_data["content"]
        elif isinstance(message_data.get("content"), list):
            # Multi-part content (Anthropic format)
            parts = []
            for part in message_data["content"]:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        parts.append(part.get("text", ""))
                    elif part.get("type") == "tool_result":
                        parts.append(part.get("content", ""))
                elif isinstance(part, str):
                    parts.append(part)
            content = "\n".join(parts)

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

        return SessionMessage(
            type=msg_type or role,
            role=role,
            content=content,
            metadata=metadata,
            turn_index=turn_index,
        )

    def to_jsonl(self, path: Path) -> None:
        """Write the archive to a JSONL file."""
        with open(path, "w", encoding="utf-8") as f:
            # Write metadata header
            meta = {**self._metadata, "_copium_compacted": self.is_compacted}
            f.write(json.dumps(meta) + "\n")

            for msg in self.messages:
                record = {
                    "type": msg.type,
                    "message": {
                        "role": msg.role,
                        "content": msg.content,
                    },
                }
                if msg.metadata:
                    record["message"].update(
                        {k: v for k, v in msg.metadata.items() if k != "tool"}
                    )
                    if "tool" in msg.metadata:
                        record["tool"] = msg.metadata["tool"]
                f.write(json.dumps(record) + "\n")

    def token_estimate(self) -> int:
        """Rough token estimate (chars / 4)."""
        total_chars = sum(len(m.content) for m in self.messages)
        return total_chars // 4

    def __len__(self) -> int:
        return len(self.messages)

    def __repr__(self) -> str:
        return f"SessionArchive(path={self.path}, messages={len(self.messages)})"
