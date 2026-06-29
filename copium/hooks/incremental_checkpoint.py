"""Incremental checkpointing — save state gradually instead of catastrophically.

Instead of one catastrophic compaction that loses everything, incremental
checkpointing saves structured state every N tool calls, creating a
"gentle slope" instead of a cliff.

Integrates with the compression pipeline via CompressionHooks to
periodically checkpoint decisions, file relationships, and task state.

Based on community proposal in anthropics/claude-code #33088:
'Rolling window that summarizes the oldest 20% of context after every
N tool calls, creating a gentle slope instead of a catastrophic cliff.'
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..hooks import CompressContext, CompressEvent, CompressionHooks

logger = logging.getLogger(__name__)


@dataclass
class Checkpoint:
    """A single incremental checkpoint capturing session state."""

    checkpoint_id: str
    turn: int
    timestamp: float
    decisions: list[str]
    active_files: list[str]
    task_state: str
    tool_calls_since_last: int
    context_usage_pct: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "turn": self.turn,
            "timestamp": self.timestamp,
            "decisions": self.decisions,
            "active_files": self.active_files,
            "task_state": self.task_state,
            "tool_calls_since_last": self.tool_calls_since_last,
            "context_usage_pct": self.context_usage_pct,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        return cls(
            checkpoint_id=data["checkpoint_id"],
            turn=data["turn"],
            timestamp=data["timestamp"],
            decisions=data["decisions"],
            active_files=data["active_files"],
            task_state=data["task_state"],
            tool_calls_since_last=data.get("tool_calls_since_last", 0),
            context_usage_pct=data.get("context_usage_pct", 0.0),
            metadata=data.get("metadata", {}),
        )

    def to_context_message(self) -> str:
        """Format checkpoint as a context message for injection."""
        parts = [f"[Session checkpoint at turn {self.turn}]"]
        if self.task_state:
            parts.append(f"Task: {self.task_state}")
        if self.decisions:
            parts.append("Decisions: " + "; ".join(self.decisions[-5:]))
        if self.active_files:
            parts.append("Active files: " + ", ".join(self.active_files[-10:]))
        return "\n".join(parts)


@dataclass
class CheckpointStoreConfig:
    """Configuration for the checkpoint store."""

    store_dir: Path = field(
        default_factory=lambda: Path.home() / ".copium" / "incremental_checkpoints"
    )
    max_checkpoints: int = 20
    checkpoint_interval: int = 10  # Every N tool calls
    context_threshold_60: float = 0.60  # Fire checkpoint at 60% usage
    context_threshold_70: float = 0.70  # Fire checkpoint at 70% usage


class IncrementalCheckpointStore:
    """Persistent store for incremental checkpoints.

    Stores checkpoints as JSON files on disk, indexed by session ID.
    Handles serialization, pruning, and retrieval.
    """

    def __init__(self, config: CheckpointStoreConfig | None = None):
        self.config = config or CheckpointStoreConfig()
        self.config.store_dir.mkdir(parents=True, exist_ok=True)

    def save(self, session_id: str, checkpoint: Checkpoint) -> Path:
        """Save a checkpoint to disk."""
        session_dir = self.config.store_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{checkpoint.turn:04d}_{checkpoint.checkpoint_id}.json"
        path = session_dir / filename
        path.write_text(
            json.dumps(checkpoint.to_dict(), indent=2),
            encoding="utf-8",
        )

        # Prune old checkpoints
        self._prune(session_dir)
        return path

    def load_latest(self, session_id: str, n: int = 1) -> list[Checkpoint]:
        """Load the N most recent checkpoints for a session."""
        session_dir = self.config.store_dir / session_id
        if not session_dir.exists():
            return []

        files = sorted(session_dir.glob("*.json"))
        checkpoints: list[Checkpoint] = []
        for path in files[-n:]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                checkpoints.append(Checkpoint.from_dict(data))
            except (json.JSONDecodeError, KeyError, OSError) as e:
                logger.warning("Failed to load checkpoint %s: %s", path, e)

        return checkpoints

    def load_all(self, session_id: str) -> list[Checkpoint]:
        """Load all checkpoints for a session."""
        return self.load_latest(session_id, n=self.config.max_checkpoints)

    def _prune(self, session_dir: Path) -> None:
        """Remove oldest checkpoints if we exceed max."""
        files = sorted(session_dir.glob("*.json"))
        while len(files) > self.config.max_checkpoints:
            oldest = files.pop(0)
            oldest.unlink(missing_ok=True)


class IncrementalCheckpointHooks(CompressionHooks):
    """Compression hooks that create incremental checkpoints.

    Fires checkpoints at regular intervals (every N tool calls) and at
    context pressure thresholds (60%, 70%). This creates a "gentle slope"
    of state preservation instead of a catastrophic cliff at compaction.
    """

    def __init__(
        self,
        config: CheckpointStoreConfig | None = None,
        session_id: str = "",
    ):
        self.config = config or CheckpointStoreConfig()
        self.session_id = session_id
        self._store = IncrementalCheckpointStore(self.config)
        self._tool_call_count = 0
        self._last_checkpoint_turn = 0
        self._checkpoints: list[Checkpoint] = []
        self._fired_60 = False
        self._fired_70 = False

    def pre_compress(
        self,
        messages: list[dict[str, Any]],
        ctx: CompressContext,
    ) -> list[dict[str, Any]]:
        """Check if we should fire an incremental checkpoint."""
        self._tool_call_count += len(ctx.tool_calls) if ctx.tool_calls else 1
        calls_since_last = self._tool_call_count - self._last_checkpoint_turn

        should_checkpoint = False

        # Check interval trigger
        if calls_since_last >= self.config.checkpoint_interval:
            should_checkpoint = True

        if should_checkpoint:
            checkpoint = self._create_checkpoint(messages, ctx)
            self._save_checkpoint(checkpoint)

            # Inject checkpoint summary into messages for post-compaction recovery
            messages = list(messages)  # Don't mutate original
            messages.append({
                "role": "user",
                "content": checkpoint.to_context_message(),
            })

        return messages

    def post_compress(self, event: CompressEvent) -> None:
        """Track compression events for context pressure monitoring."""
        # Estimate context usage from compression ratio
        if event.tokens_before > 0:
            usage_pct = event.tokens_after / 200_000  # Approximate

            # Fire threshold-based checkpoints
            if usage_pct >= self.config.context_threshold_70 and not self._fired_70:
                self._fired_70 = True
                logger.info(
                    "Context at 70%% threshold — emergency checkpoint recommended"
                )
            elif usage_pct >= self.config.context_threshold_60 and not self._fired_60:
                self._fired_60 = True
                logger.info(
                    "Context at 60%% threshold — checkpoint recommended"
                )

    def get_checkpoints(self) -> list[Checkpoint]:
        """Get all checkpoints for the current session."""
        if self._checkpoints:
            return list(self._checkpoints)
        return self._store.load_all(self.session_id)

    def get_recovery_context(self, max_checkpoints: int = 3) -> str:
        """Get formatted recovery context from recent checkpoints."""
        checkpoints = self.get_checkpoints()[-max_checkpoints:]
        if not checkpoints:
            return ""

        parts = ["[Incremental Checkpoint Recovery]"]
        for cp in checkpoints:
            parts.append(cp.to_context_message())
            parts.append("---")

        return "\n".join(parts)

    def _create_checkpoint(
        self,
        messages: list[dict[str, Any]],
        ctx: CompressContext,
    ) -> Checkpoint:
        """Create a checkpoint from current state."""
        decisions = self._extract_decisions(messages)
        active_files = self._extract_active_files(messages)
        task_state = self._extract_task_state(messages, ctx)

        checkpoint_id = hashlib.sha256(
            f"{self.session_id}:{self._tool_call_count}:{time.time()}".encode()
        ).hexdigest()[:12]

        return Checkpoint(
            checkpoint_id=checkpoint_id,
            turn=self._tool_call_count,
            timestamp=time.time(),
            decisions=decisions,
            active_files=active_files,
            task_state=task_state,
            tool_calls_since_last=self._tool_call_count - self._last_checkpoint_turn,
            context_usage_pct=0.0,  # Updated in post_compress
            metadata={
                "model": ctx.model,
                "user_query": ctx.user_query[:200] if ctx.user_query else "",
            },
        )

    def _save_checkpoint(self, checkpoint: Checkpoint) -> None:
        """Save checkpoint to store and update tracking."""
        self._checkpoints.append(checkpoint)
        self._last_checkpoint_turn = self._tool_call_count

        if self.session_id:
            self._store.save(self.session_id, checkpoint)

        # Keep in-memory list bounded
        if len(self._checkpoints) > self.config.max_checkpoints:
            self._checkpoints.pop(0)

        logger.info(
            "Incremental checkpoint saved (turn %d, decisions: %d, files: %d)",
            checkpoint.turn,
            len(checkpoint.decisions),
            len(checkpoint.active_files),
        )

    def _extract_decisions(self, messages: list[dict[str, Any]]) -> list[str]:
        """Extract architectural decisions from messages."""
        decision_patterns = [
            re.compile(r"(?:decision|decided|choosing|going with|using)[:\s]+(.+)", re.IGNORECASE),
            re.compile(r"(?:approach|strategy|pattern)[:\s]+(.+)", re.IGNORECASE),
            re.compile(r"(?:rejected|ruled out|won't use)[:\s]+(.+)", re.IGNORECASE),
        ]

        decisions: list[str] = []
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            content = str(msg.get("content", ""))
            for pattern in decision_patterns:
                for match in pattern.finditer(content):
                    decision = match.group(1).strip()[:200]
                    if decision and len(decision) > 10:
                        decisions.append(decision)

        return decisions[-20:]  # Keep last 20

    def _extract_active_files(self, messages: list[dict[str, Any]]) -> list[str]:
        """Extract recently referenced file paths."""
        path_pattern = re.compile(
            r"(?:^|[\s\"'`])(/[^\s\"'`\n]+\.[a-zA-Z0-9]+)"
            r"|(?:^|[\s\"'`])(\./[^\s\"'`\n]+\.[a-zA-Z0-9]+)"
            r"|(?:^|[\s\"'`])([a-zA-Z0-9_-]+/[^\s\"'`\n]+\.[a-zA-Z0-9]+)"
        )

        paths: set[str] = set()
        # Focus on recent messages
        recent = messages[-20:]
        for msg in recent:
            content = str(msg.get("content", ""))
            for match in path_pattern.finditer(content):
                path = match.group(1) or match.group(2) or match.group(3)
                if path:
                    paths.add(path)

        return sorted(paths)[:30]

    def _extract_task_state(
        self, messages: list[dict[str, Any]], ctx: CompressContext
    ) -> str:
        """Extract current task state from recent messages."""
        if ctx.user_query:
            return ctx.user_query[:300]

        # Fall back to last user message
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = str(msg.get("content", ""))
                return content[:300]

        return ""
