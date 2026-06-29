"""Post-compaction recovery — restore session state after auto-compaction.

After Claude Code (or another agent) fires auto-compaction and replaces
the conversation history with a summary, this module restores critical
state from a pre-compaction checkpoint.

The recovery process:
1. Loads the most recent checkpoint for the session
2. Injects key context (file paths, decisions, tool output references)
3. Provides the restored context as additional system/user messages
4. Bridges with the CCR store for on-demand content retrieval
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .pre_compact_hook import (
    DEFAULT_CHECKPOINT_DIR,
    CheckpointConfig,
    PreCompactHook,
    SessionCheckpoint,
)

logger = logging.getLogger(__name__)


@dataclass
class RecoveryConfig:
    """Configuration for post-compaction recovery."""

    checkpoint_dir: Path = field(default_factory=lambda: DEFAULT_CHECKPOINT_DIR)
    max_recovery_tokens: int = 30_000
    inject_file_paths: bool = True
    inject_decisions: bool = True
    inject_tool_references: bool = True
    format: str = "anthropic"  # anthropic or openai


@dataclass
class RecoveryResult:
    """Result of a post-compaction recovery attempt."""

    session_id: str
    checkpoint_id: str | None
    messages_injected: int
    file_paths_restored: int
    decisions_restored: int
    tool_refs_restored: int
    recovery_tokens_est: int
    success: bool
    error: str | None = None


class PostCompactRecovery:
    """Restore session state after auto-compaction using saved checkpoints.

    Integrates with PreCompactHook to load checkpoints and inject
    critical context back into the conversation after compaction fires.
    """

    def __init__(self, config: RecoveryConfig | None = None):
        self.config = config or RecoveryConfig()
        self._hook = PreCompactHook(
            CheckpointConfig(checkpoint_dir=self.config.checkpoint_dir)
        )

    def recover(
        self,
        session_id: str,
        current_messages: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], RecoveryResult]:
        """Recover state from the most recent checkpoint.

        Args:
            session_id: The session to recover state for.
            current_messages: Current post-compaction messages (if any).

        Returns:
            Tuple of (recovery messages to inject, result stats).
        """
        checkpoint = self._hook.get_latest_checkpoint(session_id)
        if not checkpoint:
            return [], RecoveryResult(
                session_id=session_id,
                checkpoint_id=None,
                messages_injected=0,
                file_paths_restored=0,
                decisions_restored=0,
                tool_refs_restored=0,
                recovery_tokens_est=0,
                success=False,
                error="No checkpoint found for session",
            )

        recovery_messages = self._build_recovery_messages(checkpoint)

        result = RecoveryResult(
            session_id=session_id,
            checkpoint_id=checkpoint.checkpoint_id,
            messages_injected=len(recovery_messages),
            file_paths_restored=len(checkpoint.file_paths_mentioned),
            decisions_restored=len(checkpoint.decisions),
            tool_refs_restored=len(checkpoint.tool_output_hashes),
            recovery_tokens_est=self._estimate_tokens(recovery_messages),
            success=True,
        )

        logger.info(
            "Post-compaction recovery for session %s: "
            "%d messages, %d files, %d decisions restored",
            session_id,
            result.messages_injected,
            result.file_paths_restored,
            result.decisions_restored,
        )

        return recovery_messages, result

    def recover_from_checkpoint(
        self, checkpoint: SessionCheckpoint
    ) -> list[dict[str, Any]]:
        """Recover from a specific checkpoint."""
        return self._build_recovery_messages(checkpoint)

    def _build_recovery_messages(
        self, checkpoint: SessionCheckpoint
    ) -> list[dict[str, Any]]:
        """Build recovery messages from a checkpoint."""
        messages: list[dict[str, Any]] = []
        budget_chars = self.config.max_recovery_tokens * 4
        used_chars = 0

        # 1. Context recovery header
        header = self._build_recovery_header(checkpoint)
        used_chars += len(header)
        if used_chars <= budget_chars:
            messages.append(self._make_message("user", header))

        # 2. File paths context
        if self.config.inject_file_paths and checkpoint.file_paths_mentioned:
            paths_msg = self._build_file_paths_message(checkpoint)
            if used_chars + len(paths_msg) <= budget_chars:
                messages.append(self._make_message("user", paths_msg))
                used_chars += len(paths_msg)

        # 3. Decisions context
        if self.config.inject_decisions and checkpoint.decisions:
            decisions_msg = self._build_decisions_message(checkpoint)
            if used_chars + len(decisions_msg) <= budget_chars:
                messages.append(self._make_message("user", decisions_msg))
                used_chars += len(decisions_msg)

        # 4. Tool output references (for CCR retrieval)
        if self.config.inject_tool_references and checkpoint.tool_output_hashes:
            refs_msg = self._build_tool_refs_message(checkpoint)
            if used_chars + len(refs_msg) <= budget_chars:
                messages.append(self._make_message("user", refs_msg))
                used_chars += len(refs_msg)

        # 5. Message snapshot (remaining budget)
        remaining_budget = budget_chars - used_chars
        if remaining_budget > 500 and checkpoint.messages_snapshot:
            snapshot_msg = self._build_snapshot_message(
                checkpoint, max_chars=remaining_budget
            )
            if snapshot_msg:
                messages.append(self._make_message("user", snapshot_msg))

        return messages

    def _build_recovery_header(self, checkpoint: SessionCheckpoint) -> str:
        """Build the recovery context header."""
        age_minutes = (time.time() - checkpoint.timestamp) / 60
        return (
            f"[Copium Session Recovery]\n"
            f"This context was saved before auto-compaction fired.\n"
            f"Session: {checkpoint.session_id}\n"
            f"Model: {checkpoint.model}\n"
            f"Saved: {age_minutes:.0f} minutes ago\n"
            f"Context usage at save: {checkpoint.token_usage:,} / "
            f"{checkpoint.context_window:,} tokens "
            f"({checkpoint.metadata.get('usage_pct', 0) * 100:.1f}%)\n"
            f"---"
        )

    def _build_file_paths_message(self, checkpoint: SessionCheckpoint) -> str:
        """Build file paths recovery message."""
        paths = checkpoint.file_paths_mentioned[:50]
        lines = ["[Files referenced in this session]"]
        for p in paths:
            lines.append(f"  {p}")
        return "\n".join(lines)

    def _build_decisions_message(self, checkpoint: SessionCheckpoint) -> str:
        """Build decisions recovery message."""
        decisions = checkpoint.decisions[:20]
        lines = ["[Key decisions made in this session]"]
        for i, d in enumerate(decisions, 1):
            lines.append(f"  {i}. {d}")
        return "\n".join(lines)

    def _build_tool_refs_message(self, checkpoint: SessionCheckpoint) -> str:
        """Build tool output references message."""
        refs = list(checkpoint.tool_output_hashes.items())[:30]
        lines = [
            "[Tool outputs available via CCR store (use copium_retrieve to access)]"
        ]
        for h, desc in refs:
            lines.append(f"  [{h}] {desc}")
        return "\n".join(lines)

    def _build_snapshot_message(
        self, checkpoint: SessionCheckpoint, max_chars: int
    ) -> str | None:
        """Build message snapshot within char budget."""
        if not checkpoint.messages_snapshot:
            return None

        lines = ["[Conversation snapshot before compaction]"]
        total = len("[Conversation snapshot before compaction]\n")

        for msg in checkpoint.messages_snapshot:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in content
                )

            # Truncate individual messages
            content = str(content)[:500]
            line = f"  [{role}] {content}"

            if total + len(line) + 1 > max_chars:
                break
            lines.append(line)
            total += len(line) + 1

        return "\n".join(lines) if len(lines) > 1 else None

    def _make_message(self, role: str, content: str) -> dict[str, Any]:
        """Create a message dict in the configured format."""
        return {"role": role, "content": content}

    def _estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        """Estimate token count for messages."""
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        return total_chars // 4
