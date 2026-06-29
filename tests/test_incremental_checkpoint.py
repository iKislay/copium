"""Tests for incremental checkpointing hooks."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from copium.hooks import CompressContext, CompressEvent
from copium.hooks.incremental_checkpoint import (
    Checkpoint,
    CheckpointStoreConfig,
    IncrementalCheckpointHooks,
    IncrementalCheckpointStore,
)


@pytest.fixture
def store_dir(tmp_path):
    return tmp_path / "checkpoints"


@pytest.fixture
def config(store_dir):
    return CheckpointStoreConfig(
        store_dir=store_dir,
        max_checkpoints=5,
        checkpoint_interval=3,
    )


@pytest.fixture
def sample_messages():
    return [
        {"role": "user", "content": "Fix the bug in /src/auth/middleware.ts"},
        {
            "role": "assistant",
            "content": "Decision: Using JWT validation with RS256 for auth.",
        },
        {"role": "tool", "content": "export function auth() { return true; }\n" * 10},
        {"role": "user", "content": "Now check /src/api/routes.ts"},
        {
            "role": "assistant",
            "content": "Approach: RESTful routing with middleware chain.",
        },
        {"role": "tool", "content": "app.get('/api/users', handler)\n" * 5},
    ]


class TestCheckpoint:
    """Tests for Checkpoint dataclass."""

    def test_to_dict_roundtrip(self):
        cp = Checkpoint(
            checkpoint_id="abc123",
            turn=10,
            timestamp=1000.0,
            decisions=["Use JWT", "Use PostgreSQL"],
            active_files=["/src/auth.ts", "/src/db.ts"],
            task_state="Fixing authentication bug",
            tool_calls_since_last=5,
            context_usage_pct=0.65,
        )
        data = cp.to_dict()
        restored = Checkpoint.from_dict(data)

        assert restored.checkpoint_id == cp.checkpoint_id
        assert restored.turn == cp.turn
        assert restored.decisions == cp.decisions
        assert restored.active_files == cp.active_files

    def test_to_context_message(self):
        cp = Checkpoint(
            checkpoint_id="abc123",
            turn=10,
            timestamp=1000.0,
            decisions=["Use JWT for auth"],
            active_files=["/src/auth.ts"],
            task_state="Fixing authentication",
            tool_calls_since_last=5,
            context_usage_pct=0.65,
        )
        msg = cp.to_context_message()

        assert "turn 10" in msg
        assert "Fixing authentication" in msg
        assert "JWT" in msg
        assert "/src/auth.ts" in msg


class TestIncrementalCheckpointStore:
    """Tests for IncrementalCheckpointStore."""

    def test_save_and_load(self, config):
        store = IncrementalCheckpointStore(config)
        cp = Checkpoint(
            checkpoint_id="test123",
            turn=5,
            timestamp=time.time(),
            decisions=["Decision A"],
            active_files=["/src/main.ts"],
            task_state="Working on feature",
            tool_calls_since_last=5,
            context_usage_pct=0.5,
        )

        store.save("session-1", cp)
        loaded = store.load_latest("session-1")

        assert len(loaded) == 1
        assert loaded[0].checkpoint_id == "test123"

    def test_load_latest_n(self, config):
        store = IncrementalCheckpointStore(config)

        for i in range(5):
            cp = Checkpoint(
                checkpoint_id=f"cp{i}",
                turn=i * 5,
                timestamp=time.time() + i,
                decisions=[f"Decision {i}"],
                active_files=[],
                task_state=f"Task {i}",
                tool_calls_since_last=5,
                context_usage_pct=0.0,
            )
            store.save("session-1", cp)

        latest_2 = store.load_latest("session-1", n=2)
        assert len(latest_2) == 2
        assert latest_2[-1].checkpoint_id == "cp4"

    def test_pruning(self, store_dir):
        config = CheckpointStoreConfig(store_dir=store_dir, max_checkpoints=3)
        store = IncrementalCheckpointStore(config)

        for i in range(5):
            cp = Checkpoint(
                checkpoint_id=f"cp{i}",
                turn=i,
                timestamp=time.time() + i,
                decisions=[],
                active_files=[],
                task_state="",
                tool_calls_since_last=1,
                context_usage_pct=0.0,
            )
            store.save("session-1", cp)

        all_cps = store.load_all("session-1")
        assert len(all_cps) <= 3

    def test_load_nonexistent_session(self, config):
        store = IncrementalCheckpointStore(config)
        assert store.load_latest("nonexistent") == []


class TestIncrementalCheckpointHooks:
    """Tests for IncrementalCheckpointHooks."""

    def test_fires_checkpoint_at_interval(self, config, sample_messages):
        hooks = IncrementalCheckpointHooks(config=config, session_id="test-session")
        ctx = CompressContext(
            model="claude-sonnet-4",
            user_query="Fix bugs",
            tool_calls=["read_file"],
        )

        # First 2 calls should not checkpoint (interval=3)
        hooks.pre_compress(sample_messages, ctx)
        hooks.pre_compress(sample_messages, ctx)
        assert len(hooks._checkpoints) == 0

        # Third call should trigger checkpoint
        result = hooks.pre_compress(sample_messages, ctx)
        assert len(hooks._checkpoints) == 1

    def test_checkpoint_contains_decisions(self, config, sample_messages):
        hooks = IncrementalCheckpointHooks(config=config, session_id="test-session")
        ctx = CompressContext(
            model="claude-sonnet-4",
            tool_calls=["read_file", "grep", "bash"],
        )

        # Trigger checkpoint
        hooks.pre_compress(sample_messages, ctx)
        hooks.pre_compress(sample_messages, ctx)
        hooks.pre_compress(sample_messages, ctx)

        cp = hooks._checkpoints[0]
        assert len(cp.decisions) > 0

    def test_checkpoint_contains_file_paths(self, config, sample_messages):
        hooks = IncrementalCheckpointHooks(config=config, session_id="test-session")
        ctx = CompressContext(
            model="claude-sonnet-4",
            tool_calls=["read_file", "read_file", "read_file"],
        )

        hooks.pre_compress(sample_messages, ctx)
        hooks.pre_compress(sample_messages, ctx)
        hooks.pre_compress(sample_messages, ctx)

        cp = hooks._checkpoints[0]
        assert any("auth" in f or "routes" in f for f in cp.active_files)

    def test_injects_checkpoint_message(self, config, sample_messages):
        hooks = IncrementalCheckpointHooks(config=config, session_id="test-session")
        ctx = CompressContext(
            model="claude-sonnet-4",
            tool_calls=["read_file", "grep", "bash"],
        )

        hooks.pre_compress(sample_messages, ctx)
        hooks.pre_compress(sample_messages, ctx)
        result = hooks.pre_compress(sample_messages, ctx)

        # Should have injected a checkpoint message
        assert len(result) == len(sample_messages) + 1
        assert "[Session checkpoint" in result[-1]["content"]

    def test_get_recovery_context(self, config, sample_messages):
        hooks = IncrementalCheckpointHooks(config=config, session_id="test-session")
        ctx = CompressContext(
            model="claude-sonnet-4",
            user_query="Fix the auth bug",
            tool_calls=["read", "write", "test"],
        )

        # Trigger a checkpoint
        hooks.pre_compress(sample_messages, ctx)
        hooks.pre_compress(sample_messages, ctx)
        hooks.pre_compress(sample_messages, ctx)

        recovery = hooks.get_recovery_context()
        assert "Checkpoint Recovery" in recovery
        assert len(recovery) > 0

    def test_persists_to_disk(self, config, sample_messages):
        hooks = IncrementalCheckpointHooks(config=config, session_id="test-session")
        ctx = CompressContext(
            model="claude-sonnet-4",
            tool_calls=["a", "b", "c"],
        )

        hooks.pre_compress(sample_messages, ctx)
        hooks.pre_compress(sample_messages, ctx)
        hooks.pre_compress(sample_messages, ctx)

        # Verify on disk
        session_dir = config.store_dir / "test-session"
        assert session_dir.exists()
        assert len(list(session_dir.glob("*.json"))) == 1

    def test_max_checkpoints_enforced(self, store_dir, sample_messages):
        config = CheckpointStoreConfig(
            store_dir=store_dir,
            max_checkpoints=2,
            checkpoint_interval=1,
        )
        hooks = IncrementalCheckpointHooks(config=config, session_id="test-session")
        ctx = CompressContext(
            model="claude-sonnet-4",
            tool_calls=["x"],
        )

        for _ in range(5):
            hooks.pre_compress(sample_messages, ctx)

        assert len(hooks._checkpoints) <= 2

    def test_post_compress_tracks_usage(self, config):
        hooks = IncrementalCheckpointHooks(config=config, session_id="test")
        event = CompressEvent(
            tokens_before=180_000,
            tokens_after=140_000,
            tokens_saved=40_000,
        )
        # Should not raise
        hooks.post_compress(event)

    def test_empty_session_no_recovery(self, config):
        hooks = IncrementalCheckpointHooks(config=config, session_id="empty")
        assert hooks.get_recovery_context() == ""
        assert hooks.get_checkpoints() == []
