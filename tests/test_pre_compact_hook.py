"""Tests for pre-compaction hook and post-compaction recovery."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from copium.proxy.compaction_detector import CompactionEvent
from copium.proxy.pre_compact_hook import (
    CheckpointConfig,
    PreCompactHook,
    SessionCheckpoint,
)
from copium.proxy.post_compact_recovery import (
    PostCompactRecovery,
    RecoveryConfig,
    RecoveryResult,
)


@pytest.fixture
def checkpoint_dir(tmp_path):
    return tmp_path / "checkpoints"


@pytest.fixture
def sample_messages():
    return [
        {"role": "user", "content": "Fix the bug in /src/auth/middleware.ts"},
        {
            "role": "assistant",
            "content": "I'll fix the authentication middleware. "
            "Decision: Using JWT validation with RS256 algorithm.",
        },
        {
            "role": "tool",
            "content": "export function authenticate(req: Request) {\n"
            "  const token = req.headers.authorization;\n"
            "  // validate token\n" * 20,
        },
        {"role": "user", "content": "Now run the tests with pytest tests/test_auth.py -v"},
        {
            "role": "assistant",
            "content": "Going with pytest for the auth tests. Let me run them.",
        },
        {
            "role": "tool",
            "content": "PASSED test_auth_valid\nPASSED test_auth_expired\n" * 10,
        },
    ]


@pytest.fixture
def compaction_event():
    return CompactionEvent(
        session_id="test-session-123",
        model="claude-opus-4",
        token_usage=170_000,
        context_window=200_000,
        threshold=0.835,
        usage_pct=0.85,
    )


class TestPreCompactHook:
    """Tests for PreCompactHook."""

    @pytest.mark.asyncio
    async def test_creates_checkpoint(
        self, checkpoint_dir, compaction_event, sample_messages
    ):
        config = CheckpointConfig(checkpoint_dir=checkpoint_dir)
        hook = PreCompactHook(config)

        checkpoint = await hook.on_compaction_imminent(
            compaction_event, sample_messages
        )

        assert checkpoint is not None
        assert checkpoint.session_id == "test-session-123"
        assert checkpoint.model == "claude-opus-4"
        assert checkpoint.token_usage == 170_000
        assert compaction_event.checkpoint_saved is True

    @pytest.mark.asyncio
    async def test_extracts_file_paths(
        self, checkpoint_dir, compaction_event, sample_messages
    ):
        config = CheckpointConfig(checkpoint_dir=checkpoint_dir)
        hook = PreCompactHook(config)

        checkpoint = await hook.on_compaction_imminent(
            compaction_event, sample_messages
        )

        assert "/src/auth/middleware.ts" in checkpoint.file_paths_mentioned

    @pytest.mark.asyncio
    async def test_extracts_decisions(
        self, checkpoint_dir, compaction_event, sample_messages
    ):
        config = CheckpointConfig(checkpoint_dir=checkpoint_dir)
        hook = PreCompactHook(config)

        checkpoint = await hook.on_compaction_imminent(
            compaction_event, sample_messages
        )

        assert len(checkpoint.decisions) > 0
        assert any("JWT" in d or "authentication" in d for d in checkpoint.decisions)

    @pytest.mark.asyncio
    async def test_extracts_tool_output_hashes(
        self, checkpoint_dir, compaction_event, sample_messages
    ):
        config = CheckpointConfig(checkpoint_dir=checkpoint_dir)
        hook = PreCompactHook(config)

        checkpoint = await hook.on_compaction_imminent(
            compaction_event, sample_messages
        )

        assert len(checkpoint.tool_output_hashes) > 0

    @pytest.mark.asyncio
    async def test_saves_to_disk(
        self, checkpoint_dir, compaction_event, sample_messages
    ):
        config = CheckpointConfig(checkpoint_dir=checkpoint_dir)
        hook = PreCompactHook(config)

        await hook.on_compaction_imminent(compaction_event, sample_messages)

        session_dir = checkpoint_dir / "test-session-123"
        assert session_dir.exists()
        checkpoint_files = list(session_dir.glob("*.json"))
        assert len(checkpoint_files) == 1

    @pytest.mark.asyncio
    async def test_max_checkpoints_enforced(
        self, checkpoint_dir, sample_messages
    ):
        config = CheckpointConfig(
            checkpoint_dir=checkpoint_dir, max_checkpoints_per_session=2
        )
        hook = PreCompactHook(config)

        for i in range(3):
            event = CompactionEvent(
                session_id="test-session",
                model="claude-opus-4",
                token_usage=170_000 + i * 1000,
                context_window=200_000,
                threshold=0.835,
                usage_pct=0.85,
                timestamp=time.time() + i,
            )
            await hook.on_compaction_imminent(event, sample_messages)

        # Should only keep last 2 in memory
        checkpoints = hook._checkpoints.get("test-session", [])
        assert len(checkpoints) == 2

    def test_get_latest_checkpoint(self, checkpoint_dir, sample_messages):
        config = CheckpointConfig(checkpoint_dir=checkpoint_dir)
        hook = PreCompactHook(config)

        # No checkpoint yet
        assert hook.get_latest_checkpoint("nonexistent") is None

    def test_list_checkpoints_empty(self, checkpoint_dir):
        config = CheckpointConfig(checkpoint_dir=checkpoint_dir)
        hook = PreCompactHook(config)
        assert hook.list_checkpoints("nonexistent") == []

    @pytest.mark.asyncio
    async def test_checkpoint_roundtrip(
        self, checkpoint_dir, compaction_event, sample_messages
    ):
        config = CheckpointConfig(checkpoint_dir=checkpoint_dir)
        hook = PreCompactHook(config)

        saved = await hook.on_compaction_imminent(compaction_event, sample_messages)

        # Load from disk (new hook instance)
        hook2 = PreCompactHook(config)
        loaded = hook2.get_latest_checkpoint("test-session-123")

        assert loaded is not None
        assert loaded.session_id == saved.session_id
        assert loaded.model == saved.model
        assert loaded.file_paths_mentioned == saved.file_paths_mentioned


class TestPostCompactRecovery:
    """Tests for PostCompactRecovery."""

    @pytest.mark.asyncio
    async def test_recovery_from_checkpoint(
        self, checkpoint_dir, compaction_event, sample_messages
    ):
        # First save a checkpoint
        hook_config = CheckpointConfig(checkpoint_dir=checkpoint_dir)
        hook = PreCompactHook(hook_config)
        await hook.on_compaction_imminent(compaction_event, sample_messages)

        # Now recover
        recovery_config = RecoveryConfig(checkpoint_dir=checkpoint_dir)
        recovery = PostCompactRecovery(recovery_config)
        messages, result = recovery.recover("test-session-123")

        assert result.success is True
        assert result.messages_injected > 0
        assert result.file_paths_restored > 0
        assert len(messages) > 0

    def test_recovery_no_checkpoint(self, checkpoint_dir):
        config = RecoveryConfig(checkpoint_dir=checkpoint_dir)
        recovery = PostCompactRecovery(config)
        messages, result = recovery.recover("nonexistent-session")

        assert result.success is False
        assert result.error is not None
        assert messages == []

    @pytest.mark.asyncio
    async def test_recovery_contains_file_paths(
        self, checkpoint_dir, compaction_event, sample_messages
    ):
        hook_config = CheckpointConfig(checkpoint_dir=checkpoint_dir)
        hook = PreCompactHook(hook_config)
        await hook.on_compaction_imminent(compaction_event, sample_messages)

        recovery_config = RecoveryConfig(checkpoint_dir=checkpoint_dir)
        recovery = PostCompactRecovery(recovery_config)
        messages, result = recovery.recover("test-session-123")

        # Check that file paths are in the recovery messages
        all_content = " ".join(m.get("content", "") for m in messages)
        assert "/src/auth/middleware.ts" in all_content

    @pytest.mark.asyncio
    async def test_recovery_respects_max_tokens(
        self, checkpoint_dir, compaction_event, sample_messages
    ):
        hook_config = CheckpointConfig(checkpoint_dir=checkpoint_dir)
        hook = PreCompactHook(hook_config)
        await hook.on_compaction_imminent(compaction_event, sample_messages)

        # Very small token budget
        recovery_config = RecoveryConfig(
            checkpoint_dir=checkpoint_dir, max_recovery_tokens=100
        )
        recovery = PostCompactRecovery(recovery_config)
        messages, result = recovery.recover("test-session-123")

        # Should still succeed but with fewer messages
        assert result.success is True
        total_chars = sum(len(m.get("content", "")) for m in messages)
        assert total_chars < 500  # 100 tokens * 4 chars + overhead


class TestSessionCheckpoint:
    """Tests for SessionCheckpoint data class."""

    def test_checkpoint_id_is_deterministic(self):
        cp = SessionCheckpoint(
            session_id="test",
            model="claude",
            timestamp=1234567890.0,
            token_usage=100_000,
            context_window=200_000,
            messages_snapshot=[],
            file_paths_mentioned=[],
            decisions=[],
            tool_output_hashes={},
        )
        # Same inputs produce same ID
        cp2 = SessionCheckpoint(
            session_id="test",
            model="claude",
            timestamp=1234567890.0,
            token_usage=100_000,
            context_window=200_000,
            messages_snapshot=[],
            file_paths_mentioned=[],
            decisions=[],
            tool_output_hashes={},
        )
        assert cp.checkpoint_id == cp2.checkpoint_id

    def test_to_dict_and_from_dict(self):
        cp = SessionCheckpoint(
            session_id="test-session",
            model="claude-opus-4",
            timestamp=1234567890.0,
            token_usage=170_000,
            context_window=200_000,
            messages_snapshot=[{"role": "user", "content": "hello"}],
            file_paths_mentioned=["/src/main.py"],
            decisions=["Use async/await pattern"],
            tool_output_hashes={"abc123": "file content..."},
        )

        data = cp.to_dict()
        restored = SessionCheckpoint.from_dict(data)

        assert restored.session_id == cp.session_id
        assert restored.model == cp.model
        assert restored.file_paths_mentioned == cp.file_paths_mentioned
        assert restored.decisions == cp.decisions
        assert restored.tool_output_hashes == cp.tool_output_hashes
