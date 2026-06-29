"""Pre-compaction hook — save session state before auto-compaction fires.

When the CompactionDetector signals that compaction is imminent, this hook
captures a durable state checkpoint containing:
- Deduplicated tool outputs (with CCR hash keys)
- Key decisions and architecture notes
- Modified file paths and their states
- Active test commands and configurations
- The user's stated goals and constraints

The checkpoint is stored as compressed JSONL and can be restored after
compaction via the PostCompactRecovery module.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .compaction_detector import CompactionEvent

logger = logging.getLogger(__name__)

# Default checkpoint directory
DEFAULT_CHECKPOINT_DIR = Path.home() / ".copium" / "checkpoints"


@dataclass
class CheckpointConfig:
    """Configuration for pre-compaction checkpoints."""

    checkpoint_dir: Path = field(default_factory=lambda: DEFAULT_CHECKPOINT_DIR)
    max_checkpoints_per_session: int = 5
    include_tool_outputs: bool = True
    include_file_paths: bool = True
    include_decisions: bool = True
    max_checkpoint_tokens: int = 50_000


@dataclass
class SessionCheckpoint:
    """A saved state checkpoint from before compaction."""

    session_id: str
    model: str
    timestamp: float
    token_usage: int
    context_window: int
    messages_snapshot: list[dict[str, Any]]
    file_paths_mentioned: list[str]
    decisions: list[str]
    tool_output_hashes: dict[str, str]  # hash -> brief description
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def checkpoint_id(self) -> str:
        """Unique checkpoint identifier."""
        raw = f"{self.session_id}:{self.timestamp}"
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "session_id": self.session_id,
            "model": self.model,
            "timestamp": self.timestamp,
            "token_usage": self.token_usage,
            "context_window": self.context_window,
            "messages_snapshot": self.messages_snapshot,
            "file_paths_mentioned": self.file_paths_mentioned,
            "decisions": self.decisions,
            "tool_output_hashes": self.tool_output_hashes,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionCheckpoint:
        return cls(
            session_id=data["session_id"],
            model=data["model"],
            timestamp=data["timestamp"],
            token_usage=data["token_usage"],
            context_window=data["context_window"],
            messages_snapshot=data["messages_snapshot"],
            file_paths_mentioned=data["file_paths_mentioned"],
            decisions=data["decisions"],
            tool_output_hashes=data["tool_output_hashes"],
            metadata=data.get("metadata", {}),
        )


class PreCompactHook:
    """Save session state before auto-compaction fires.

    Integrates with CompactionDetector to create checkpoints when
    compaction is imminent. Checkpoints capture the essential state
    that compaction typically destroys (file paths, decisions, etc.).
    """

    def __init__(self, config: CheckpointConfig | None = None):
        self.config = config or CheckpointConfig()
        self.config.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._checkpoints: dict[str, list[SessionCheckpoint]] = {}

    async def on_compaction_imminent(
        self,
        event: CompactionEvent,
        messages: list[dict[str, Any]],
    ) -> SessionCheckpoint:
        """Create a state checkpoint before compaction fires.

        Args:
            event: The compaction detection event.
            messages: Current conversation messages.

        Returns:
            The saved checkpoint.
        """
        # Extract critical state from messages
        file_paths = self._extract_file_paths(messages)
        decisions = self._extract_decisions(messages)
        tool_hashes = self._extract_tool_output_hashes(messages)

        # Create snapshot (last N messages that fit in budget)
        snapshot = self._create_snapshot(messages)

        checkpoint = SessionCheckpoint(
            session_id=event.session_id,
            model=event.model,
            timestamp=time.time(),
            token_usage=event.token_usage,
            context_window=event.context_window,
            messages_snapshot=snapshot,
            file_paths_mentioned=file_paths,
            decisions=decisions,
            tool_output_hashes=tool_hashes,
            metadata={
                "usage_pct": event.usage_pct,
                "tokens_remaining": event.tokens_remaining,
            },
        )

        # Save to disk
        self._save_checkpoint(checkpoint)

        # Track in memory
        session_checkpoints = self._checkpoints.setdefault(event.session_id, [])
        session_checkpoints.append(checkpoint)

        # Enforce max checkpoints per session
        if len(session_checkpoints) > self.config.max_checkpoints_per_session:
            session_checkpoints.pop(0)

        event.checkpoint_saved = True

        logger.info(
            "Pre-compaction checkpoint saved for session %s "
            "(files: %d, decisions: %d, tool hashes: %d)",
            event.session_id,
            len(file_paths),
            len(decisions),
            len(tool_hashes),
        )

        return checkpoint

    def get_latest_checkpoint(self, session_id: str) -> SessionCheckpoint | None:
        """Get the most recent checkpoint for a session."""
        # Check memory first
        if session_id in self._checkpoints and self._checkpoints[session_id]:
            return self._checkpoints[session_id][-1]

        # Check disk
        return self._load_latest_checkpoint(session_id)

    def list_checkpoints(self, session_id: str) -> list[SessionCheckpoint]:
        """List all checkpoints for a session."""
        checkpoints = []
        session_dir = self.config.checkpoint_dir / session_id
        if session_dir.exists():
            for path in sorted(session_dir.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    checkpoints.append(SessionCheckpoint.from_dict(data))
                except (json.JSONDecodeError, KeyError, OSError) as e:
                    logger.warning("Failed to load checkpoint %s: %s", path, e)
        return checkpoints

    def _save_checkpoint(self, checkpoint: SessionCheckpoint) -> Path:
        """Save checkpoint to disk."""
        session_dir = self.config.checkpoint_dir / checkpoint.session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{int(checkpoint.timestamp)}_{checkpoint.checkpoint_id}.json"
        path = session_dir / filename
        path.write_text(
            json.dumps(checkpoint.to_dict(), indent=2),
            encoding="utf-8",
        )
        logger.debug("Checkpoint saved to %s", path)
        return path

    def _load_latest_checkpoint(self, session_id: str) -> SessionCheckpoint | None:
        """Load the most recent checkpoint from disk."""
        session_dir = self.config.checkpoint_dir / session_id
        if not session_dir.exists():
            return None

        checkpoint_files = sorted(session_dir.glob("*.json"))
        if not checkpoint_files:
            return None

        try:
            data = json.loads(checkpoint_files[-1].read_text(encoding="utf-8"))
            return SessionCheckpoint.from_dict(data)
        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.warning("Failed to load checkpoint: %s", e)
            return None

    def _extract_file_paths(self, messages: list[dict[str, Any]]) -> list[str]:
        """Extract file paths mentioned in messages."""
        import re

        path_pattern = re.compile(
            r"(?:^|[\s\"'`])(/[^\s\"'`\n]+\.[a-zA-Z0-9]+)"
            r"|(?:^|[\s\"'`])(\./[^\s\"'`\n]+\.[a-zA-Z0-9]+)"
            r"|(?:^|[\s\"'`])([a-zA-Z0-9_-]+/[^\s\"'`\n]+\.[a-zA-Z0-9]+)"
        )

        paths: set[str] = set()
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in content
                )
            for match in path_pattern.finditer(str(content)):
                path = match.group(1) or match.group(2) or match.group(3)
                if path:
                    paths.add(path)

        return sorted(paths)[:100]  # Cap at 100 paths

    def _extract_decisions(self, messages: list[dict[str, Any]]) -> list[str]:
        """Extract key decisions from assistant messages."""
        import re

        decision_patterns = [
            re.compile(r"(?:I(?:'ll| will)|Let's|We should|The (?:best|right) approach is)(.{20,150})", re.IGNORECASE),
            re.compile(r"(?:Decision|Approach|Strategy|Plan):?\s*(.{20,150})", re.IGNORECASE),
            re.compile(r"(?:Going with|Choosing|Selected|Using)(.{20,150})", re.IGNORECASE),
        ]

        decisions: list[str] = []
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in content
                )
            for pattern in decision_patterns:
                for match in pattern.finditer(str(content)):
                    decision = match.group(0).strip()
                    if decision and len(decision) > 20:
                        decisions.append(decision[:200])

        return decisions[:50]  # Cap at 50 decisions

    def _extract_tool_output_hashes(
        self, messages: list[dict[str, Any]]
    ) -> dict[str, str]:
        """Extract tool output content hashes with brief descriptions."""
        hashes: dict[str, str] = {}

        for msg in messages:
            if msg.get("role") != "tool" and not (
                msg.get("role") == "user"
                and isinstance(msg.get("content"), list)
                and any(
                    isinstance(p, dict) and p.get("type") == "tool_result"
                    for p in msg.get("content", [])
                )
            ):
                continue

            content = msg.get("content", "")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "tool_result":
                        text = part.get("content", "")
                        if len(text) > 50:
                            h = hashlib.sha256(text.encode()).hexdigest()[:16]
                            hashes[h] = text[:80] + "..."
            elif isinstance(content, str) and len(content) > 50:
                h = hashlib.sha256(content.encode()).hexdigest()[:16]
                hashes[h] = content[:80] + "..."

        return dict(list(hashes.items())[:200])  # Cap at 200 hashes

    def _create_snapshot(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Create a message snapshot within token budget."""
        # Estimate 4 chars per token
        budget_chars = self.config.max_checkpoint_tokens * 4
        snapshot: list[dict[str, Any]] = []
        total_chars = 0

        # Take messages from the end (most recent first)
        for msg in reversed(messages):
            content = msg.get("content", "")
            if isinstance(content, list):
                content_len = sum(
                    len(p.get("text", "")) if isinstance(p, dict) else len(str(p))
                    for p in content
                )
            else:
                content_len = len(str(content))

            if total_chars + content_len > budget_chars:
                break

            snapshot.insert(0, msg)
            total_chars += content_len

        return snapshot
