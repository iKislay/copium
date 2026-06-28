"""Aider JSONL session adapter.

Parses Aider's conversation history stored as JSONL files in
~/.aider/conversations/ or project-local .aider.chat.history.md.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..archive import SessionMessage

logger = logging.getLogger(__name__)


class AiderAdapter:
    """Parse Aider JSONL/markdown session files."""

    name = "aider"

    def detect(self, path: Path) -> bool:
        """Detect Aider session format.

        Aider uses JSONL with {"role": "user"|"assistant", "content": "..."}
        and typically includes "aider" in file path or has specific metadata.
        Also supports .aider.chat.history.md markdown format.
        """
        # Markdown format
        if path.name.endswith(".aider.chat.history.md"):
            return True

        if path.suffix != ".jsonl":
            return False

        # Check if path contains "aider"
        if "aider" in str(path).lower():
            return True

        # Check file content
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    # Aider format: simple role/content without "type" wrapper
                    if (
                        isinstance(data, dict)
                        and "role" in data
                        and "content" in data
                        and "type" not in data
                        and "message" not in data
                    ):
                        return True
                    break
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return False
        return False

    def parse(self, path: Path) -> list[SessionMessage]:
        """Parse Aider session into unified messages."""
        if path.name.endswith(".aider.chat.history.md"):
            return self._parse_markdown(path)
        return self._parse_jsonl(path)

    def write(self, messages: list[SessionMessage], path: Path) -> None:
        """Write messages in Aider JSONL format."""
        with open(path, "w", encoding="utf-8") as f:
            for msg in messages:
                record = {
                    "role": msg.role,
                    "content": msg.content,
                }
                if msg.metadata:
                    record.update(
                        {k: v for k, v in msg.metadata.items() if k != "tool"}
                    )
                f.write(json.dumps(record) + "\n")

    def _parse_jsonl(self, path: Path) -> list[SessionMessage]:
        """Parse Aider JSONL format."""
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

                if not isinstance(data, dict) or "role" not in data:
                    continue

                role = data["role"]
                content = data.get("content", "")
                if not content:
                    continue

                msg_type = role
                if role == "function":
                    role = "tool"
                    msg_type = "tool_result"

                metadata: dict[str, Any] = {}
                if "model" in data:
                    metadata["model"] = data["model"]
                if "timestamp" in data:
                    metadata["timestamp"] = data["timestamp"]

                messages.append(
                    SessionMessage(
                        type=msg_type,
                        role=role,
                        content=content,
                        metadata=metadata,
                        turn_index=turn_index,
                    )
                )

                if role in ("user", "assistant"):
                    turn_index += 1

        logger.info("Aider adapter: parsed %d messages from %s", len(messages), path)
        return messages

    def _parse_markdown(self, path: Path) -> list[SessionMessage]:
        """Parse Aider markdown chat history format.

        Format:
        #### user
        message content

        #### assistant
        response content
        """
        messages: list[SessionMessage] = []
        turn_index = 0
        current_role = ""
        current_content: list[str] = []

        text = path.read_text(encoding="utf-8")
        lines = text.split("\n")

        for line in lines:
            if line.startswith("#### "):
                # Flush previous message
                if current_role and current_content:
                    content = "\n".join(current_content).strip()
                    if content:
                        messages.append(
                            SessionMessage(
                                type=current_role,
                                role=current_role,
                                content=content,
                                turn_index=turn_index,
                            )
                        )
                        if current_role in ("user", "assistant"):
                            turn_index += 1

                # Start new message
                current_role = line[5:].strip().lower()
                if current_role not in ("user", "assistant", "system"):
                    current_role = "assistant"
                current_content = []
            else:
                current_content.append(line)

        # Flush last message
        if current_role and current_content:
            content = "\n".join(current_content).strip()
            if content:
                messages.append(
                    SessionMessage(
                        type=current_role,
                        role=current_role,
                        content=content,
                        turn_index=turn_index,
                    )
                )

        logger.info("Aider adapter: parsed %d messages from %s", len(messages), path)
        return messages
